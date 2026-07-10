"""
Golden prompts (specs.md) : chargement des cas (`tests/golden_prompts.yaml`) et évaluation d'une
réponse `/solutions` contre un cas.

Module de production (pas un fichier de test) car réutilisé par deux appelants différents :
- `tests/test_golden_prompts.py` : pilote la vraie API en HTTP (boîte noire, cf. ce fichier).
- `dags/tasks/rag_ingestion.py::run_golden_prompts_gate` : porte de qualité avant promotion en
  prod, appelle `generate_treatment_advice()` directement en process (comme `_run_ingestion` pour
  l'ingestion elle-même) plutôt que de dépendre d'un serveur HTTP rag-llm démarré dans le
  conteneur Airflow.

Centraliser la logique évite que les deux appelants divergent au fil du temps.
"""
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.dosage_rules import compute_dosage

FALLBACK_MARKER = "informations disponibles"  # aucun chunk pgvector trouvé (le bug qu'on vérifie)
LLM_ERROR_MARKER = "detail technique"  # chunks trouvés, mais l'appel LLM lui-même a échoué (quota/API HF)

GOLDEN_PROMPTS_PATH = Path(__file__).resolve().parents[1] / "tests" / "golden_prompts.yaml"


class GoldenPromptFailure(AssertionError):
    """Le cas a réellement échoué : maladie non résolue, dosage divergent, mot-clé absent."""


class GoldenPromptSkipped(Exception):
    """
    Seule la vérification dépendant du LLM externe n'a pas pu être faite (quota/API HF
    indisponible) — hors de portée de ce test, qui vérifie la résolution du nommage/dosage, pas
    la disponibilité du LLM.
    """


def normalize_text(text: Optional[str]) -> str:
    """Minuscules + suppression des accents, pour un matching robuste au phrasé du LLM."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def load_cases(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = path or GOLDEN_PROMPTS_PATH
    return yaml.safe_load(path.read_text())["cases"]


def build_payload(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cnn_label": case["cnn_label"],
        "mode": case["mode"],
        "severity": case["severity"],
        "area_m2": case["area_m2"],
    }


def evaluate_case(data: Dict[str, Any], case: Dict[str, Any]) -> None:
    """
    Vérifie une réponse `/solutions` (dict `data`, HTTP ou appel direct de
    `generate_treatment_advice()`) contre un cas golden prompt.

    Lève `GoldenPromptFailure` si la maladie n'a pas été résolue (fallback générique) ou si le
    dosage diverge d'un appel direct de `compute_dosage()`. Lève `GoldenPromptSkipped` si tout le
    reste est correct mais que seule la vérification des mots-clés LLM ne peut être faite (LLM
    indisponible). Ne retourne rien si le cas est entièrement validé.
    """
    diagnostic_norm = normalize_text(data.get("diagnostic", ""))

    if case.get("expect_fallback"):
        if FALLBACK_MARKER not in diagnostic_norm:
            raise GoldenPromptFailure(
                f"Fallback générique attendu (fiche supprimée) mais diagnostic = {data.get('diagnostic')!r}"
            )
        if data.get("treatment_plan") != {}:
            raise GoldenPromptFailure(f"treatment_plan attendu vide, reçu {data.get('treatment_plan')!r}")
        return

    if FALLBACK_MARKER in diagnostic_norm:
        raise GoldenPromptFailure(
            "Réponse tombée sur le message de repli générique — la fiche n'a pas été retrouvée dans "
            f"pgvector pour cnn_label={case['cnn_label']!r}. Diagnostic: {data.get('diagnostic')!r}"
        )

    treatment_plan = data.get("treatment_plan") or {}
    if not treatment_plan:
        raise GoldenPromptFailure("treatment_plan vide alors qu'un fallback n'était pas attendu")

    if "expect_configured" in case and treatment_plan.get("configured") != case["expect_configured"]:
        raise GoldenPromptFailure(
            f"configured={treatment_plan.get('configured')!r}, attendu {case['expect_configured']!r}"
        )

    if case.get("expect_dose_zero") and treatment_plan.get("dose_l_ha") != 0.0:
        raise GoldenPromptFailure(f"dose_l_ha={treatment_plan.get('dose_l_ha')!r}, attendu 0.0")

    # Cross-check : le dosage renvoyé doit être identique à un appel direct de compute_dosage()
    # avec les mêmes paramètres (détecte toute divergence de résolution du cnn_label).
    reference = compute_dosage(case["cnn_label"], case["mode"], case["area_m2"], severity=case["severity"])
    if treatment_plan.get("dose_l_ha") != reference.get("dose_l_ha"):
        raise GoldenPromptFailure(
            f"dose_l_ha={treatment_plan.get('dose_l_ha')!r}, attendu {reference.get('dose_l_ha')!r} "
            "(divergence avec un appel direct de compute_dosage())"
        )
    if treatment_plan.get("volume_bouillie_l_ha") != reference.get("volume_bouillie_l_ha"):
        raise GoldenPromptFailure(
            f"volume_bouillie_l_ha={treatment_plan.get('volume_bouillie_l_ha')!r}, "
            f"attendu {reference.get('volume_bouillie_l_ha')!r}"
        )

    if "expect_cnn_label_fr" in case and data.get("cnn_label_fr") != case["expect_cnn_label_fr"]:
        raise GoldenPromptFailure(
            f"cnn_label_fr={data.get('cnn_label_fr')!r}, attendu {case['expect_cnn_label_fr']!r}"
        )

    expected_keywords = case.get("expect_keywords", [])
    if expected_keywords:
        if LLM_ERROR_MARKER in diagnostic_norm:
            raise GoldenPromptSkipped(
                f"Appel LLM indisponible ({data.get('diagnostic')!r}) — mots-clés non vérifiables."
            )
        if not any(normalize_text(kw) in diagnostic_norm for kw in expected_keywords):
            raise GoldenPromptFailure(
                f"Aucun des mots-clés attendus {expected_keywords} trouvé dans le diagnostic LLM: "
                f"{data.get('diagnostic')!r}"
            )
