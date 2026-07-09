from typing import List, Dict


def build_treatment_prompt(
    cnn_label: str,
    disease_name_fr: str,
    mode: str,
    severity: str,
    area_m2: float,
    season: str,
    context_chunks: List[Dict[str, str]],
) -> str:
    """
    Construit le prompt envoyé au LLM pour générer un plan d'action viticole.

    On attend une réponse STRICTEMENT au format JSON valide, avec 4 champs :
    - diagnostic: str
    - treatment_actions: List[str]
    - preventive_actions: List[str]
    - warnings: List[str]
    """
    contexte = "\n\n---\n\n".join([c["text"] for c in context_chunks])

    prompt = f"""
Tu es un expert viticole spécialisé dans la protection de la vigne.

Contexte de la situation :
- Maladie détectée (label CNN) : "{cnn_label}"
- Maladie (nom détaillé) : "{disease_name_fr}"
- Mode de conduite : "{mode}"
- Gravité : "{severity}"
- Surface concernée : {area_m2} m²
- Saison : "{season}"

Base de connaissances (extraits de fiches techniques) :
{contexte}

Ta tâche est de :
1) Proposer un DIAGNOSTIC synthétique.
2) Proposer des ACTIONS DE TRAITEMENT concrètes et applicables.
3) Proposer des MESURES PRÉVENTIVES pour la suite de la saison.
4) Rappeler les AVERTISSEMENTS de sécurité ou de réglementation.

CONTRAINTE TRÈS IMPORTANTE :
Tu dois répondre avec un UNIQUE objet JSON, valide, SANS texte avant ou après, SANS explication.
Utilise exactement les clés suivantes :

{{
  "diagnostic": "texte court (3 à 5 phrases max) expliquant la situation.",
  "treatment_actions": [
    "Action de traitement 1 (précise, opérationnelle).",
    "Action de traitement 2."
  ],
  "preventive_actions": [
    "Action préventive 1.",
    "Action préventive 2."
  ],
  "warnings": [
    "Avertissement 1 (sécurité, réglementation, délais avant récolte, etc.).",
    "Avertissement 2."
  ]
}}

Règles :
- Écris en français.
- Reste concret, clair et opérationnel pour un viticulteur.
- Ne parle pas de toi, ne t'excuse pas, ne remercie pas.
- Ne mets PAS de ```json ou de balise de code autour du JSON.
- Ne mets PAS de virgule finale après le dernier élément d'une liste.
- Ne mets AUCUN texte en dehors du JSON.

FORMAT (OBLIGATOIRE) :
- "treatment_actions", "preventive_actions" et "warnings" doivent être des tableaux JSON (List[str]) uniquement.
- Interdiction de représenter une liste sous forme d'objet avec des clés "0:", "1:", etc.
- Interdiction d'utiliser des listes Markdown (ex: "- ...", "* ...", "1) ...").
- Chaque élément de liste doit être une chaîne de caractères simple, sans préfixe de numérotation.
- Chaque élément doit faire 1 à 2 phrases max, et éviter les formats "Action: ..." (pas de paires clé/valeur).
- Vise 2 à 6 éléments par liste.
- Avant de répondre, vérifie que ton JSON passe un json.loads.

Répond maintenant en fournissant uniquement l'objet JSON.
"""
    return prompt.strip()
