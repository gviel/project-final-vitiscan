#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
else
    DOCKER_COMPOSE=(docker-compose)
fi

# Doit matcher start.sh, sinon docker-compose ne retrouve pas les conteneurs du bon projet
# (et pire, pourrait cibler par erreur ceux d'une autre stack "airflow" par défaut).
export COMPOSE_PROJECT_NAME=vitiscan_airflow

"${DOCKER_COMPOSE[@]}" down
