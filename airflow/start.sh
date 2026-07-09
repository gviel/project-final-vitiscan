#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Compatibilité docker compose v2 (plugin) / docker-compose v1 (binaire autonome)
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
else
    DOCKER_COMPOSE=(docker-compose)
fi

# CRITIQUE : sans ceci, le nom de projet Compose par défaut serait "airflow" (nom de ce dossier),
# identique à celui de la stack Airflow du projet Fraud Detection déjà en cours d'exécution sur
# cette machine -> collision de conteneurs/volumes. Ne jamais retirer cette ligne.
export COMPOSE_PROJECT_NAME=vitiscan_airflow

export AIRFLOW_UID=$(id -u)

ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERREUR : airflow/$ENV_FILE introuvable (copier airflow/.env.template)." >&2
    exit 1
fi
for _var in RAG_S3_BUCKET RAG_S3_PREFIX WEAVIATE_PROD_HOST WEAVIATE_PROD_PORT WEAVIATE_API_KEY \
            DAG_RAG_INGESTION_CRON AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION \
            MLFLOW_URI EXPERIMENT_NAME TRAINING_S3_BUCKET \
            HF_API_URL HF_API_TOKEN HF_MODEL_ID; do
    if [ -z "${!_var:-}" ]; then
        export "$_var=$(grep -E "^${_var}=" "$ENV_FILE" | tail -1 | cut -d= -f2-)"
    fi
done

echo "=== Vitiscan — Airflow 3.2.2 (projet Compose: $COMPOSE_PROJECT_NAME) ==="
echo "AIRFLOW_UID=$AIRFLOW_UID"

mkdir -p logs plugins config

if ! "${DOCKER_COMPOSE[@]}" ps airflow-init 2>/dev/null | grep -q "Exit"; then
    echo ""
    echo "--- Initialisation Airflow (première fois) ---"
    "${DOCKER_COMPOSE[@]}" up --build airflow-init
fi

echo ""
echo "--- Démarrage des services ---"
"${DOCKER_COMPOSE[@]}" up -d --build

echo ""
echo "--- Attente du démarrage de l'API server ---"
for i in $(seq 1 20); do
    if curl -sf http://localhost:8090/api/v2/version >/dev/null 2>&1; then
        echo "✓ Airflow UI prête : http://localhost:8090  (airflow / airflow)"
        break
    fi
    printf "."
    sleep 3
done

echo ""
echo "Services actifs :"
"${DOCKER_COMPOSE[@]}" ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"
