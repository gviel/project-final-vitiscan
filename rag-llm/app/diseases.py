"""Référentiel unique des maladies (labels CNN, alias, traductions FR).

Auparavant dupliqué (avec de légères variantes) entre dosage_rules.py et rag_pipeline.py.
"""
from typing import Dict

# Alias courts hérités (anglais court, PlantVillage/Kaggle) -> label canonique.
# Le label canonique est soit le nom latin du taxon INRAE (ex: "guignardia_bidwellii"), soit le nom
# de classe Kaggle tel quel pour les 2 maladies sans équivalent INRAE ("brown_spot", "shot_hole").
# Gardé pour compat ascendante (ex: champ debug de l'UI où un alias court est tapé à la main) — un
# label déjà canonique (latin ou Kaggle) passe inchangé via le fallback de normalize_cnn_label.
CNN_LABEL_ALIASES: Dict[str, str] = {
    "anthracnose": "elsinoe_ampelina",
    "black_rot": "guignardia_bidwellii",
    "downy_mildew": "plasmopara_viticola",
    "erinose": "colomerus_vitis",
    "esca": "phaeomoniella_chlamydospora",
    "normal": "sain",
    "powdery_mildew": "erysiphe_necator",
}

# Traduction FR pour affichage (prompt LLM, réponse API)
DISEASE_FR: Dict[str, str] = {
    "elsinoe_ampelina": "Anthracnose",
    "guignardia_bidwellii": "Pourriture noire de la vigne",
    "brown_spot": "Tâche brune",
    "plasmopara_viticola": "Mildiou",
    "colomerus_vitis": "Érinose de la vigne",
    "phaeomoniella_chlamydospora": "Esca de la vigne",
    "sain": "Pas de maladie",
    "erysiphe_necator": "Oïdium",
    "shot_hole": "Coryneum",
}


def normalize_cnn_label(raw: str) -> str:
    """Convertit un alias court hérité ou un nom de fichier en label canonique."""
    if not raw:
        return raw
    label = str(raw).strip()
    if label.endswith(".md"):
        label = label[: -len(".md")]
    return CNN_LABEL_ALIASES.get(label.lower(), label)


def cnn_label_to_fr(raw_label: str) -> str:
    """Traduit un alias court hérité ou un label canonique en nom FR affichable."""
    if not raw_label:
        return raw_label
    return DISEASE_FR.get(normalize_cnn_label(raw_label).lower(), raw_label)
