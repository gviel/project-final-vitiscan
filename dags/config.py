"""Configuration partagée entre les DAGs et les tâches (Variables Airflow > env)."""
import os
from pathlib import Path

from airflow.models import Variable


def _var(key: str, default: str) -> str:
    return Variable.get(key, default_var=os.getenv(key, default))


# ── RAG-LLM : ingestion des documents de connaissance ────────────────────────────
# Bucket dédié aux données Vitiscan (dataset, disease.json, docs RAG) - plus l'ancien bucket
# MLflow "aws-s3-mlflow", réutilisé par erreur comme zone de dépôt (cf. docs/refactoring.md).
# knowledge/current/ = docs actuellement utilisés par le RAG en prod ; knowledge/new/ = zone de
# dépôt de nouveaux docs (pas encore de logique de promotion new/ -> current/, cf. specs.md).
RAG_S3_BUCKET = _var("RAG_S3_BUCKET", "s3-vitiscan-data")
RAG_S3_PREFIX = _var("RAG_S3_PREFIX", "knowledge/current/")
RAG_LLM_DIR   = Path(_var("RAG_LLM_DIR", "/opt/airflow/rag-llm"))

# Neon Postgres/pgvector : une branche "test" et une branche "prod" (branching natif Neon,
# copy-on-write), créées manuellement au préalable - reproduit l'isolation qu'offraient les 2
# instances Weaviate test/prod, sans avoir besoin de host.docker.internal (Neon est joignable
# directement par URL, contrairement à l'ancien Weaviate "prod" du docker-compose.yml racine).
DATABASE_URL_TEST = _var("DATABASE_URL_TEST", "")
DATABASE_URL_PROD = _var("DATABASE_URL_PROD", "")

# URL Render du service vitiscan-rag-llm-test (cf. render.yaml) - même code que vitiscan-rag-llm
# mais branché sur DATABASE_URL_TEST. Interrogé en HTTP par run_golden_prompts_gate pour rejouer
# les golden prompts contre le vrai service déployé, pas seulement contre les données.
RAG_LLM_TEST_URL = _var("RAG_LLM_TEST_URL", "")

AWS_ACCESS_KEY_ID     = _var("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = _var("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION    = _var("AWS_DEFAULT_REGION", "eu-west-3")

DAG_RAG_INGESTION_CRON = _var("DAG_RAG_INGESTION_CRON", "0 * * * *")

# ── Répertoire de travail générique ───────────────────────────────────────────────
# Bind-mount de work/ (racine du dépôt, gitignoré) plutôt qu'un volume Docker nommé : fichiers de
# travail (cache dataset, cache téléchargement knowledge...) visibles/inspectables depuis l'hôte,
# persistants entre recréations de conteneur, pas besoin de retélécharger ni de purge manuelle
# après coup (cf. airflow/docker-compose.yml, dags/tasks/rag_ingestion.py).
WORK_DIR = Path(_var("WORK_DIR", "/opt/airflow/work"))

# ── Training : sweep multi-modèles CNN (dag_train_model) ─────────────────────────
TRAINING_DIR         = Path(_var("TRAINING_DIR", "/opt/airflow/training"))
TRAINING_CONFIG_PATH = TRAINING_DIR / "config.yml"
# Sous WORK_DIR (cf. ci-dessus) : cache du dataset téléchargé, persistant entre déclenchements du
# DAG (cf. data_utils.py::prepare_dataset).
TRAINING_DATA_DIR = Path(_var("TRAINING_DATA_DIR", str(WORK_DIR / "training-data")))

MLFLOW_URI      = _var("MLFLOW_URI", "https://gviel-mlflow37.hf.space/")
EXPERIMENT_NAME = _var("EXPERIMENT_NAME", "Vitiscan_CNN_Resnet_INRAE")
# Bucket données Vitiscan (dataset zip + disease.json de référence, dossiers data-inrae/data-kaggle)
# - distinct du bucket MLflow "aws-s3-mlflow" (implicite, utilisé par le SDK MLflow pour pousser/
# servir le modèle, jamais paramétré explicitement par nom dans ce projet).
TRAINING_S3_BUCKET = _var("TRAINING_S3_BUCKET", "s3-vitiscan-data")
