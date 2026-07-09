# Vitiscan

Détection de maladies de la vigne par photo de feuille (CNN) + préconisation d'un plan de traitement
via un RAG-LLM.

Voir [`specs.md`](specs.md) pour le contexte complet et la roadmap.

## Structure du projet

```
api/        API FastAPI de prédiction CNN (charge le modèle depuis MLflow)
ui/         Interface Streamlit (upload photo -> diagnostic -> plan de traitement)
rag-llm/    API RAG-LLM (préconisation de traitement) + base de connaissances (data/knowledge/)
            + scripts d'ingestion + tests golden prompts (tests/)
training/   Scripts d'entraînement du modèle CNN (train.py paramétrable), loggés dans MLflow
airflow/    Stack Airflow (Dockerfile, docker-compose.yml) pour l'orchestration
dags/       DAGs Airflow (ingestion RAG + porte de qualité golden prompts, sweep multi-modèles CNN)
docs/       Documentation (audit nommage, suivi de refactoring, déploiement)
test_ui/    Scripts + photos annotées pour tester manuellement l'API de prédiction (EXIF GPS/date)
render.yaml Blueprint Render (déploiement api/ + rag-llm/, cf. docs/deploiement-render-streamlit.md)
work/       Fichiers de travail montés en volume dans Airflow (cache dataset, cache knowledge) -
            gitignoré, créé automatiquement au premier démarrage de la stack Airflow
```

Chaque composant a son propre `requirements.txt` et `.env.template` (copier en `.env` et compléter en local,
jamais commité).

MLflow est déployé séparément sur Hugging Face Spaces et n'est pas géré par ce dépôt.

## Nommage des maladies

Les 9 fiches de `rag-llm/data/knowledge/` utilisent un identifiant canonique unique (nom de fichier
= `id` = `cnn_label`) : le nom latin du taxon INRAE pour les 7 maladies du modèle en prod (ex.
`guignardia_bidwellii`), ou le nom de classe Kaggle tel quel pour les 2 maladies sans équivalent
INRAE (`brown_spot`, `shot_hole`). Détail de la décision et de l'audit qui l'a précédée :
[`docs/harmonisation-noms-maladies.md`](docs/harmonisation-noms-maladies.md).

## Démarrage rapide (local)

```bash
docker-compose up --build
```

> L'environnement de dev de référence pour ce projet n'a que `docker-compose` v1 (legacy, commande
> avec un tiret) — pas le plugin `docker compose` v2. Si votre machine a le plugin v2, `docker
> compose up --build` fonctionne aussi.

Services exposés : `api` (4000), `ui` (8502), `rag-llm` (9000), `weaviate` (8081 REST / 50051 gRPC).
Voir `docker-compose.yml` pour le détail.

## Tests

```bash
cd rag-llm && pip install -r requirements.txt -r requirements-test.txt
python -m app.ingestion          # ingère data/knowledge/ dans Weaviate (stack démarrée au préalable)
pytest tests/                    # golden prompts : vérifie retrieval + dosage + (si HF_API_TOKEN valide) diagnostic LLM
```

## Documentation

- [`docs/harmonisation-noms-maladies.md`](docs/harmonisation-noms-maladies.md) — audit et résolution du nommage des maladies
- [`docs/refactoring.md`](docs/refactoring.md) — suivi détaillé du refactoring CDSD -> ce dépôt
- [`docs/deploiement-render-streamlit.md`](docs/deploiement-render-streamlit.md) — déploiement en production (Render / Streamlit Community Cloud)
