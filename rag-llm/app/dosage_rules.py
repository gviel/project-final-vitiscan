from typing import Dict, Any, Optional
import re

from app.diseases import CNN_LABEL_ALIASES

# Règles de dosage par maladie et par mode (conventionnel / bio).
DOSAGE_RULES: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {
    "plasmopara_viticola": {
        "conventionnel": {"dose_l_ha": 1.6, "volume_bouillie_l_ha": 250.0},
        "bio": {"dose_l_ha": 2.8, "volume_bouillie_l_ha": 300.0},
    },
    "erysiphe_necator": {
        "conventionnel": {"dose_l_ha": 0.8, "volume_bouillie_l_ha": 220.0},
        "bio": {"dose_l_ha": 6.0, "volume_bouillie_l_ha": 250.0},
    },
    "elsinoe_ampelina": {
        "conventionnel": {"dose_l_ha": 2.0, "volume_bouillie_l_ha": 250.0},
        "bio": {"dose_l_ha": 3.0, "volume_bouillie_l_ha": 300.0},
    },
    "brown_spot": {
        "conventionnel": {"dose_l_ha": 1.2, "volume_bouillie_l_ha": 200.0},
        "bio": {"dose_l_ha": 1.0, "volume_bouillie_l_ha": 200.0},
    },
    "shot_hole": {
        "conventionnel": {"dose_l_ha": 1.0, "volume_bouillie_l_ha": 180.0},
        "bio": {"dose_l_ha": 2.2, "volume_bouillie_l_ha": 220.0},
    },
    "sain": {
        "conventionnel": {"dose_l_ha": 0.0, "volume_bouillie_l_ha": 0.0},
        "bio": {"dose_l_ha": 0.0, "volume_bouillie_l_ha": 0.0},
    },
    "guignardia_bidwellii": {
        "conventionnel": {"dose_l_ha": 1.5, "volume_bouillie_l_ha": 250.0},
        "bio": {"dose_l_ha": 2.5, "volume_bouillie_l_ha": 300.0},
    },
    "colomerus_vitis": {
        "conventionnel": {"dose_l_ha": 0.9, "volume_bouillie_l_ha": 180.0},
        "bio": {"dose_l_ha": 1.2, "volume_bouillie_l_ha": 200.0},
    },
    "phaeomoniella_chlamydospora": {
        "conventionnel": {"dose_l_ha": None, "volume_bouillie_l_ha": 200.0},
        "bio": {"dose_l_ha": None, "volume_bouillie_l_ha": 200.0},
    },
}

TREATMENT_PRODUCTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "plasmopara_viticola": {
        "conventionnel": {
            "type": "anti-mildiou (fongicides)",
            "examples": [
                "famille CAA (ex: diméthomorphe)",
                "famille QoI (ex: azoxystrobine)",
                "produits de contact (ex: folpel)"
            ],
            "dose_unit": "kg/ha ou L/ha (selon formulation)",
            "strategy": "préventif + renfort après pluie",
            "note": "Alterner les familles (modes d’action) pour limiter les résistances. Renforcer la cadence si pluies répétées."
        },
        "bio": {
            "type": "cuivre / biocontrôle",
            "examples": [
                "cuivre (hydroxyde de cuivre / bouillie bordelaise)",
                "phosphonates selon réglementation locale",
                "stimulateurs de défenses naturelles (SDN)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Le cuivre est surtout préventif : viser les périodes à risque (mouillures). Respecter les plafonds réglementaires annuels."
        },
    },

    "erysiphe_necator": {
        "conventionnel": {
            "type": "anti-oïdium (fongicides)",
            "examples": [
                "triazoles (ex: myclobutanil / tébuconazole)",
                "strobilurines (QoI)",
                "soufre (en complément si compatible)"
            ],
            "dose_unit": "kg/ha ou L/ha",
            "strategy": "préventif strict",
            "note": "L’oïdium ne se rattrape pas : priorité à la régularité. Rotation des modes d’action indispensable."
        },
        "bio": {
            "type": "soufre / biocontrôle",
            "examples": [
                "soufre mouillable",
                "bicarbonate de potassium",
                "huiles végétales (selon conditions)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Soufre efficace mais risque de brûlures si fortes chaleurs. Adapter l’intervalle selon météo et pression."
        },
    },

    "elsinoe_ampelina": {
        "conventionnel": {
            "type": "fongicide de contact",
            "examples": [
                "mancozèbe (si autorisé localement)",
                "folpel",
                "cuivre (selon stratégie)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Intervenir tôt sur tissus jeunes (périodes humides). Sécuriser après épisodes pluvieux et croissance rapide."
        },
        "bio": {
            "type": "cuivre / biocontrôle",
            "examples": [
                "cuivre (hydroxyde / bouillie bordelaise)",
                "biocontrôle (extraits végétaux selon homologation)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Efficacité très dépendante de la régularité et de la météo (pluie = lessivage). Renforcer l’aération."
        },
    },

    "brown_spot": {
        "conventionnel": {
            "type": "produit de contact (secondaire)",
            "examples": [
                "folpel",
                "dithiocarbamates (selon réglementation)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "opportuniste",
            "note": "Maladie souvent secondaire : traiter surtout si l’année est très humide et si défoliation progresse."
        },
        "bio": {
            "type": "biocontrôle / conduite culturale",
            "examples": [
                "bicarbonate de potassium (selon homologation)",
                "SDN (stimulateurs de défenses naturelles)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Priorité à l’aération et à la réduction du stress. Traitements légers si progression rapide."
        },
    },

    "shot_hole": {
        "conventionnel": {
            "type": "contact (faible priorité)",
            "examples": [
                "folpel",
                "cuivre (selon programme)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif léger",
            "note": "Souvent mineur : éviter les traitements inutiles. Protéger surtout jeunes vignes si année très humide."
        },
        "bio": {
            "type": "cuivre (préventif)",
            "examples": [
                "cuivre (bouillie bordelaise / hydroxyde)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Efficace surtout avant apparition des perforations. Aération et hygiène foliaire recommandées."
        },
    },

    "sain": {
        "conventionnel": {
            "type": "aucun",
            "examples": [],
            "dose_unit": "",
            "strategy": "aucune",
            "note": "Aucun traitement nécessaire. Maintenir la surveillance."
        },
        "bio": {
            "type": "aucun",
            "examples": [],
            "dose_unit": "",
            "strategy": "aucune",
            "note": "Aucun traitement nécessaire. Maintenir la surveillance."
        },
    },

    "guignardia_bidwellii": {
        "conventionnel": {
            "type": "anti-black rot (fongicides)",
            "examples": [
                "dithiocarbamates (selon réglementation)",
                "strobilurines (QoI)",
                "fongicides de contact (ex: captan / folpel selon dispo)"
            ],
            "dose_unit": "kg/ha ou L/ha",
            "strategy": "préventif + renfort après pluie",
            "note": "Cibler les périodes à risque (pluie/chaleur). Bien couvrir les grappes et renouveler après lessivage."
        },
        "bio": {
            "type": "cuivre / biocontrôle",
            "examples": [
                "cuivre (bouillie bordelaise / hydroxyde)",
                "SDN (stimulateurs de défenses naturelles)"
            ],
            "dose_unit": "kg/ha",
            "strategy": "préventif",
            "note": "Protection surtout préventive. Renforcer la prophylaxie (aération, gestion des débris infectés)."
        },
    },

    "colomerus_vitis": {
        "conventionnel": {
            "type": "acaricide / anti-acariens",
            "examples": [
                "abamectine (selon homologation)",
                "hexythiazox (selon homologation)",
                "spirodiclofène (selon homologation)"
            ],
            "dose_unit": "L/ha",
            "strategy": "ciblé",
            "note": "Traiter tôt si forte pression. Éviter les traitements systématiques pour préserver les auxiliaires."
        },
        "bio": {
            "type": "huiles / savon / soufre",
            "examples": [
                "huile paraffinique (huiles blanches)",
                "savon noir (effet mécanique)",
                "soufre (effet partiel)"
            ],
            "dose_unit": "L/ha",
            "strategy": "réduction de pression",
            "note": "Efficacité surtout mécanique : viser le bon stade, excellente couverture, répétition possible."
        },
    },

    "phaeomoniella_chlamydospora": {
        "conventionnel": {
            "type": "pas de traitement curatif direct",
            "examples": [
                "taille sanitaire / chirurgie du tronc (selon pratique)",
                "remplacement des ceps atteints (si nécessaire)"
            ],
            "dose_unit": "",
            "strategy": "prophylaxie + gestion du vignoble",
            "note": "Esca = maladie du bois : l’approche est surtout agronomique (hygiène, réduction des blessures, gestion des ceps)."
        },
        "bio": {
            "type": "pas de traitement curatif direct",
            "examples": [
                "prophylaxie (hygiène de taille)",
                "gestion du stress hydrique et aération"
            ],
            "dose_unit": "",
            "strategy": "prophylaxie",
            "note": "Même logique : maladie du bois. Surveillance + mesures culturales ; traitement “produit” non standard."
        },
    },
}

SEVERITY_MULTIPLIER = {
    "faible": 0.75,
    "moderee": 1.0,
    "modérée": 1.0,
    "forte": 1.4,
}


def _normalize_cnn_label(raw_label: str) -> str:
    """
    Normalise uniquement le nom de la maladie vers une clé de DOSAGE_RULES.
    Accepte :
    - alias courts hérités ("anthracnose")
    - labels canoniques ("elsinoe_ampelina")
    - noms de fichiers ("elsinoe_ampelina.md")
    """
    if not raw_label:
        return raw_label

    label = str(raw_label).strip()
    label = re.sub(r"\.md$", "", label, flags=re.IGNORECASE)

    return CNN_LABEL_ALIASES.get(label.lower(), label)


def format_treatment_product(product: Dict[str, Any]) -> list[str]:
    """Transforme un treatment_product dict en liste de bullet points lisibles."""
    if not product:
        return []

    bullets = []
    if product.get("type"):
        bullets.append(f"Type de produit : {product['type']}")
    if product.get("examples"):
        bullets.append(f"Exemples : {', '.join(product['examples'])}")
    if product.get("dose_unit"):
        bullets.append(f"Unité indicative : {product['dose_unit']}")
    if product.get("strategy"):
        bullets.append(f"Stratégie : {product['strategy']}")
    if product.get("note"):
        bullets.append(f"Note : {product['note']}")

    return bullets


def compute_dosage(
    cnn_label: str,
    mode: str,
    area_m2: float,
    severity: Optional[str] = None,
    safety_margin: float = 0.10,
) -> Dict[str, Any]:
    """
    Calcule les volumes à préparer à partir :
    - d'un label de maladie (cnn_label),
    - d'un mode (bio ou conventionnel),
    - d'une surface en m²,
    - d'une marge de sécurité (10 % par défaut).
    """
    cnn_label_norm = _normalize_cnn_label(cnn_label)

    if cnn_label_norm not in DOSAGE_RULES or mode not in DOSAGE_RULES[cnn_label_norm]:
        return {}

    rules = DOSAGE_RULES[cnn_label_norm][mode]

    dose_l_ha = rules.get("dose_l_ha")
    mult = SEVERITY_MULTIPLIER.get((severity or "").strip().lower(), 1.0)
    dose_l_ha_eff = (dose_l_ha or 0.0) * mult

    volume_bouillie_l_ha = float(rules.get("volume_bouillie_l_ha") or 0.0)
    fraction_ha = area_m2 / 10_000.0

    if (dose_l_ha == 0.0 and volume_bouillie_l_ha == 0.0) or volume_bouillie_l_ha == 0.0:
        return {
            "area_m2": area_m2,
            "dose_l_ha": round(dose_l_ha_eff, 2),
            "volume_bouillie_l_ha": volume_bouillie_l_ha,
            "estimated_product_l_for_area": 0.0,
            "estimated_volume_l_for_area": 0.0,
            "configured": True,
            "note": "Aucun traitement nécessaire pour ce niveau de sévérité.",
        }

    if dose_l_ha is None:
        bouillie_l = volume_bouillie_l_ha * fraction_ha
        bouillie_l *= 1.0 + safety_margin

        treatment_product = TREATMENT_PRODUCTS.get(cnn_label_norm, {}).get(mode)

        return {
            "area_m2": area_m2,
            "dose_l_ha": None,
            "volume_bouillie_l_ha": volume_bouillie_l_ha,
            "estimated_product_l_for_area": None,
            "estimated_volume_l_for_area": round(bouillie_l, 2),
            "treatment_product": format_treatment_product(treatment_product),
            "configured": False,
            "note": "Dose non configurée pour ce label/mode. Renseigner dose_l_ha dans DOSAGE_RULES.",
        }

    produit_l = dose_l_ha_eff * fraction_ha
    bouillie_l = volume_bouillie_l_ha * fraction_ha

    produit_l *= 1.0 + safety_margin
    bouillie_l *= 1.0 + safety_margin

    treatment_product = TREATMENT_PRODUCTS.get(cnn_label_norm, {}).get(mode)

    return {
        "area_m2": area_m2,
        "dose_l_ha": round(dose_l_ha_eff, 2),
        "volume_bouillie_l_ha": volume_bouillie_l_ha,
        "estimated_product_l_for_area": round(produit_l, 2),
        "estimated_volume_l_for_area": round(bouillie_l, 2),
        "treatment_product": format_treatment_product(treatment_product),
        "configured": True,
    }
