"""
Tâches du DAG de sweep multi-modèles CNN (`training/config.yml` -> un `train.py` par modèle).

Suit le précédent du projet Fraud Detection (`dag_train_model`) : lancement en subprocess, dans
le conteneur Airflow lui-même (deps ML de `training/requirements.txt` installées directement dans
l'image, cf. `airflow/Dockerfile` - pas de conteneur Docker séparé, jugé trop complexe pour ce
projet).
Ici c'est Airflow qui orchestre la boucle multi-modèles (une tâche par modèle, via dynamic task mapping),
alors que `train.py` reste volontairement un script "un seul modèle à la fois" (cf. `training/README.md`)
"""
import subprocess
import sys
from typing import Any, Dict, List, Optional

import yaml

from config import EXPERIMENT_NAME, MLFLOW_URI, TRAINING_CONFIG_PATH, TRAINING_DATA_DIR, TRAINING_DIR, TRAINING_S3_BUCKET


def load_models_to_run() -> List[Dict[str, Any]]:
    """
    Lit `training/config.yml` et fusionne chaque entrée de `models_to_run` avec
    `default_training` (les clés du modèle surchargent les valeurs par défaut). Appelé au
    *parsing* du DAG (fichier statique monté en lecture seule) : la liste retournée alimente le
    dynamic task mapping de `dag_train_model.py`.
    """
    with TRAINING_CONFIG_PATH.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    defaults = raw.get("default_training", {})
    models = raw.get("models_to_run", [])

    return [{**defaults, **model} for model in models]


def _parse_limit_batches(value: Any) -> Optional[int]:
    """Normalise la valeur (potentiellement templatisée Jinja) du DAG param `limit_batches`."""
    if value in (None, "", "None"):
        return None
    return int(value)


def train_one_model(model_cfg: Dict[str, Any], limit_batches: Any = None) -> Dict[str, Any]:
    """
    Lance `python train.py --model ...` en subprocess pour un modèle (une entrée fusionnée par
    `load_models_to_run()`). Sortie standard héritée -> visible telle quelle dans les logs de la
    tâche Airflow. Lève `CalledProcessError` si le training échoue - n'empêche pas les autres
    modèles du sweep de s'exécuter (tâches indépendantes issues du dynamic task mapping).
    """
    model_name = model_cfg["name"]
    dataset_name = model_cfg.get("dataset_name", "inrae")
    limit_batches = _parse_limit_batches(limit_batches)

    argv = [
        sys.executable, str(TRAINING_DIR / "train.py"),
        "--model", model_name,
        "--epochs", str(model_cfg.get("epochs", 25)),
        "--patience", str(model_cfg.get("patience", 5)),
        "--batch-size", str(model_cfg.get("batch_size", 32)),
        "--learning-rate", str(model_cfg.get("learning_rate", 0.0001)),
        "--weight-decay", str(model_cfg.get("weight_decay", 0.0001)),
        "--freeze-base", str(bool(model_cfg.get("freeze_base", True))).lower(),
        "--dataset-name", dataset_name,
        "--data-dir", str(TRAINING_DATA_DIR / f"data-{dataset_name}"),
        "--mlflow-uri", MLFLOW_URI,
        "--experiment-name", EXPERIMENT_NAME,
        "--s3-bucket", TRAINING_S3_BUCKET,
    ]
    if limit_batches:
        argv += ["--limit-batches", str(limit_batches)]

    print(f"[train_model] {model_name} ({dataset_name}): {' '.join(argv)}")
    subprocess.run(argv, cwd=TRAINING_DIR, check=True)

    return {"model": model_name, "dataset_name": dataset_name}
