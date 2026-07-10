import json
from datetime import datetime
from typing import Dict, Any, List, Optional
import re

from app.dosage_rules import compute_dosage
from app.vector_store import db_client, search_treatment_chunks
from app.prompts import build_treatment_prompt
from app.llm_client import call_llm, LLMError
from app.diseases import DISEASE_FR, cnn_label_to_fr, normalize_cnn_label

DEBUG = False


def _to_str_list(value: Any) -> List[str]:
    """
    Convertit une valeur en liste de chaînes propres.
    - list -> nettoie
    - str  -> split si multi-lignes / puces, sinon [str]
    - autre -> []
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        # Si le LLM a renvoyé une liste sous forme de texte (puces ou lignes)
        if "\n" in s or s.lstrip().startswith(("-", "•")):
            lines = []
            for line in s.splitlines():
                line = line.strip().lstrip("-• ").strip()
                if line:
                    lines.append(line)
            return lines
        return [s]

    return []


def parse_llm_structured_response(raw: str) -> Dict[str, Any]:
    """
    Parsing robuste :
    - retire ```json
    - extrait le premier objet JSON {...}
    - tente json.loads (avec support JSON doublement encodé)
    - fallback heuristique si JSON invalide
    - normalise les champs en listes
    """
    default = {
        "diagnostic": raw.strip() if raw else "",
        "treatment_actions": [],
        "preventive_actions": [],
        "warnings": [],
    }

    if not raw or not raw.strip():
        return default

    text = raw.strip()

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1].strip()
        text = text.replace("json\n", "").replace("json\r\n", "").strip()

    candidate = _extract_first_json_object(text)
    if not candidate:
        # JSON tronqué : on tente au moins d'extraire des champs avec la méthode heuristique
        data = _heuristic_parse_from_text(text)
        if any([data.get("diagnostic"), data.get("treatment_actions"), data.get("preventive_actions"), data.get("warnings")]):
            return {
                "diagnostic": (data.get("diagnostic") or "").strip(),
                "treatment_actions": _to_str_list(data.get("treatment_actions")),
                "preventive_actions": _to_str_list(data.get("preventive_actions")),
                "warnings": _to_str_list(data.get("warnings")),
            }
        return default

    candidate = (
        candidate.replace("```json", "")
        .replace("```", "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .strip()
    )
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # retire virgules finales

    try:
        data = json.loads(candidate)
        if isinstance(data, str):
            data = json.loads(data)
    except Exception:
        data = _heuristic_parse_from_text(text)

    if not isinstance(data, dict):
        return default

    return {
        "diagnostic": str(data.get("diagnostic", "")).strip() or default["diagnostic"],
        "treatment_actions": _to_str_list(data.get("treatment_actions")),
        "preventive_actions": _to_str_list(data.get("preventive_actions")),
        "warnings": _to_str_list(data.get("warnings")),
    }


def infer_season_from_date(date_iso: str) -> str:
    """Déduit une saison simplifiée à partir d'une date ISO (YYYY-MM-DD)."""
    if not date_iso:
        return "inconnue"

    try:
        month = datetime.fromisoformat(date_iso).month
    except ValueError:
        return "inconnue"

    if month in (12, 1, 2):
        return "hiver"
    if month in (3, 4, 5):
        return "printemps"
    if month in (6, 7, 8):
        return "été"
    if month in (9, 10, 11):
        return "automne"
    return "inconnue"


def _extract_first_json_object(text: str) -> Optional[str]:
    """Essaie d'extraire un objet JSON {...} depuis un texte (même s'il y a du bruit autour)."""
    if not text:
        return None

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    if start == -1:
        return None

    end = cleaned.rfind("}")
    if end == -1 or end <= start:
        return None

    return cleaned[start:end + 1]


def _heuristic_parse_from_text(text: str) -> Dict[str, Any]:
    """Fallback : si le JSON est invalide, on tente d'extraire des champs avec regex."""
    out: Dict[str, Any] = {
        "diagnostic": "",
        "treatment_actions": [],
        "preventive_actions": [],
        "warnings": [],
    }

    if not text:
        return out

    m = re.search(r'"diagnostic"\s*:\s*"([^"]*)"', text, flags=re.DOTALL)
    if m:
        out["diagnostic"] = m.group(1).replace("\\n", "\n").strip()

    def extract_list(key: str) -> List[str]:
        m2 = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
        if not m2:
            return []
        inside = m2.group(1)
        return [s.replace("\\n", "\n").strip() for s in re.findall(r'"([^"]+)"', inside)]

    out["treatment_actions"] = extract_list("treatment_actions")
    out["preventive_actions"] = extract_list("preventive_actions")
    out["warnings"] = extract_list("warnings")
    return out


def generate_treatment_advice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline principal :
    1) Déduit la saison à partir de la date.
    2) Va chercher les chunks de connaissance pertinents dans Postgres/pgvector.
    3) Construit un prompt RAG et appelle un LLM.
    4) Calcule les dosages via compute_dosage.
    5) Retourne une réponse structurée pour l'API.
    """
    cnn_label = payload["cnn_label"]
    mode = str(payload["mode"]).strip().lower()
    severity = str(payload["severity"]).strip().lower()
    area_m2 = float(payload["area_m2"])
    date_iso = payload.get("date_iso", "")

    season = infer_season_from_date(date_iso)
    cnn_label_normalized = normalize_cnn_label(cnn_label)

    # 2. Récupération des chunks dans Postgres/pgvector
    with db_client() as client:
        chunks = search_treatment_chunks(client, disease_input=cnn_label, mode=mode, severity=severity, top_k=8)
        if not chunks:
            chunks = search_treatment_chunks(client, disease_input=cnn_label_normalized, mode=None, severity=severity, top_k=8)

    # 3. Si aucun chunk, on renvoie un plan basé uniquement sur les règles de dosage.
    dosage = compute_dosage(cnn_label_normalized, mode, area_m2, severity=severity)

    if not chunks:
        return {
            "cnn_label": cnn_label,
            "mode": mode,
            "area_m2": area_m2,
            "severity": severity,
            "season": season,
            "treatment_plan": dosage,
            "diagnostic": (
                "Les informations disponibles sur cette maladie sont insuffisantes "
                "pour proposer un traitement fiable à partir de la base de connaissances. "
                "Nous vous recommandons de consulter un technicien viticole local."
            ),
            "treatment_actions": [],
            "preventive_actions": [],
            "warnings": [
                "Ces recommandations sont indicatives.",
                "Vérifiez la réglementation locale et les notices des produits avant application.",
            ],
            "raw_llm_output": "",
        }

    # 4. Construction du prompt à partir des chunks RAG.
    disease_name_fr = DISEASE_FR.get(cnn_label_normalized)
    prompt = build_treatment_prompt(
        cnn_label=cnn_label,
        disease_name_fr=disease_name_fr,
        mode=mode,
        severity=severity,
        area_m2=area_m2,
        season=season,
        context_chunks=[{"text": c["text"]} for c in chunks],
    )

    if DEBUG:
        print("\n===== PROMPT ENVOYÉ AU LLM =====\n")
        print(prompt)

    # 5. Appel au LLM Hugging Face via le wrapper + parsing structuré.
    try:
        raw_llm_text = call_llm(prompt, max_new_tokens=700, temperature=0.2, top_p=0.9)

        if DEBUG:
            print("\n===== RAW LLM TEXT =====\n")
            print(raw_llm_text)

        parsed = parse_llm_structured_response(raw_llm_text)

        if not parsed.get("diagnostic"):
            parsed["diagnostic"] = (
                "Diagnostic rapide : la situation nécessite un avis technique.\n"
                "Je n'ai pas pu générer une recommandation détaillée automatiquement.\n"
                "Veuillez consulter un conseiller viticole local.\n"
            )

    except LLMError as e:
        if DEBUG:
            print(f"\n===== ERREUR LLM =====\nErreur LLM : {e}")

        fallback_text = (
            "Diagnostic rapide : la situation nécessite un avis technique.\n"
            "Je n'ai pas pu générer une recommandation détaillée automatiquement.\n"
            "Veuillez consulter un conseiller viticole local.\n"
            f"(Détail technique : {e})\n"
        )
        parsed = {
            "diagnostic": fallback_text,
            "treatment_actions": [],
            "preventive_actions": [],
            "warnings": [],
        }
        raw_llm_text = fallback_text

    base_warnings = [
        "Ces recommandations sont indicatives.",
        "Vérifiez la réglementation locale et les notices des produits avant application.",
    ]

    result = {
        "cnn_label": cnn_label,
        "cnn_label_fr": cnn_label_to_fr(cnn_label),
        "mode": mode,
        "area_m2": area_m2,
        "severity": severity,
        "season": season,
        "treatment_plan": dosage,
        "diagnostic": parsed.get("diagnostic") or "",
        "treatment_actions": parsed.get("treatment_actions") or [],
        "preventive_actions": parsed.get("preventive_actions") or [],
        "warnings": base_warnings + (parsed.get("warnings") or []),
        "raw_llm_output": raw_llm_text,
    }

    if DEBUG:
        print("\n===== RÉPONSE FINALE RETOURNÉE PAR generate_treatment_advice =====\n")
        print(result)

    return result
