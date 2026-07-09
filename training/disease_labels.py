"""
Traductions FR des classes de maladies, par dataset.

Valeurs reprises telles quelles des notebooks de référence (notebooks/CNN_model_FT.ipynb pour
inrae, notebooks/CNN_model.ipynb pour kaggle) et confirmées identiques aux fichiers déjà présents
sur S3 (s3://s3-vitiscan-data/data-inrae/disease-inrae.json et
s3://s3-vitiscan-data/data-kaggle/disease-kaggle.json - anciennement sous
s3://aws-s3-mlflow/vitiscan-data/, cf. docs/refactoring.md).

Ce disease.json est celui poussé en tant qu'extra_files du modèle (cf. train.py) et lu par
api/app.py au chargement du modèle.
"""
from typing import Dict, List

DISEASE_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "inrae": {
        "colomerus_vitis": "Erinose",
        "elsinoe_ampelina": "Anthracnose",
        "erysiphe_necator": "Oïdium",
        "guignardia_bidwellii": "Pourriture_noire",
        "phaeomoniella_chlamydospora": "Esca",
        "plasmopara_viticola": "Mildiou",
        "sain": "Pas de maladie",
    },
    "kaggle": {
        "anthracnose": "Anthracnose",
        "brown_spot": "Tâche brune",
        "downy_mildew": "Mildiou",
        "mites": "Acariens",
        "normal": "Pas de maladie",
        "powdery_mildew": "Oïdium",
        "shot_hole": "Coryneum",
    },
}


def build_disease_json(dataset_name: str, class_names: List[str]) -> Dict[str, str]:
    """
    Mapping label -> nom affiché pour les classes réellement rencontrées dans le dataset.
    Fallback identité pour toute classe inconnue de DISEASE_TRANSLATIONS (dataset personnalisé,
    nouvelle classe...).
    """
    translations = DISEASE_TRANSLATIONS.get(dataset_name, {})
    return {name: translations.get(name, name) for name in class_names}
