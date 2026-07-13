"""
DAG Airflow

Sweep multi-modèles CNN Vitiscan
`training/config.yml` -> un `train.py` par modèle
(specs.md Partie 2 AIA - futur DAG "détecter nouvelles images -> ré-entraînement").

Déclenchement manuel uniquement (`schedule=None`) :
pas encore de détection automatique de nouvelles images labellisées
La liste des modèles est lue depuis `training/config.yml` au moment du parsing du DAG
(fichier statique monté en lecture seule, cf. `dags/config.py::TRAINING_CONFIG_PATH`) 
alimente un dynamic task mapping : une tâche Airflow "train_model" par modèle

Exécution volontairement séquentielle (`max_active_tis_per_dagrun=1`) :
chaque entraînement est CPU-only et prend déjà ~15-20 min (cf. `specs.md`, NB Important),
pas de GPU dédié dans le conteneur Airflow 
-> lancer plusieurs entraînements PyTorch en parallèle sur une seule machine risquerait une forte contention CPU/RAM

Param `limit_batches` (optionnel) : permet de déclencher un sweep "smoke test" rapide (quelques batches par modèle)
sans attendre un entraînement complet par modèle (comme `--limit-batches` de `train.py`).
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.models.param import Param
from airflow.providers.standard.operators.python import PythonOperator

from tasks.train_model import load_models_to_run, train_one_model

default_args = {
    "owner": "vitiscan",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="dag_train_model",
    description="Sweep multi-modèles CNN Vitiscan (training/config.yml -> un train.py par modèle)",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    params={
        "limit_batches": Param(
            None, type=["null", "integer"],
            description="Limite le nombre de batches/epoch, pour un sweep smoke-test rapide (vide = entraînement complet)",
        ),
    },
    tags=["vitiscan", "training"],
) as dag:

    models = load_models_to_run()

    PythonOperator.partial(
        task_id="train_model",
        python_callable=train_one_model,
        max_active_tis_per_dagrun=1,
    ).expand(
        op_kwargs=[
            {"model_cfg": model_cfg, "limit_batches": "{{ params.limit_batches }}"}
            for model_cfg in models
        ]
    )
