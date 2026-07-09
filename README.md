# Vitiscan

Détection de maladies de la vigne par photo de feuille (CNN) + préconisation d'un plan de traitement
via un RAG-LLM.

Voir [`specs.md`](specs.md) pour le contexte complet et la roadmap.

## Structure du projet

```
api/        API FastAPI de prédiction CNN (charge le modèle depuis MLflow)
ui/         Interface Streamlit (upload photo -> diagnostic -> plan de traitement)
rag-llm/    API RAG-LLM (préconisation de traitement) + scripts d'ingestion de la base de connaissance
training/   Scripts d'entraînement du modèle CNN (train.py paramétrable), loggés dans MLflow
airflow/    Stack Airflow (Dockerfile, docker-compose.yml) pour l'orchestration
dags/       DAGs Airflow (ingestion RAG, ré-entraînement, etc.)
docs/       Documentation (déploiement, architecture)
```

Chaque composant a son propre `requirements.txt` et `.env.template` (copier en `.env` et compléter en local,
jamais commité).

MLflow est déployé séparément sur Hugging Face Spaces et n'est pas géré par ce dépôt.

## Démarrage rapide (local)

```bash
docker compose up --build
```

Voir `docs/` pour le détail par composant et le déploiement en production (Render / Streamlit Community).
