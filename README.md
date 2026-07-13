# JEDHA - AIA Bloc 4 : Projet Final Vitiscan

Détection de maladies de la vigne par photo de feuille (CNN) + préconisation d'un plan de traitement
via un RAG-LLM.

Projet de certification Jedha RNCP7 Bloc 4 (Architecte IA).

Dépot GitHub : https://github.com/gviel/project-final-vitiscan

Présentation : docs/AIA_bloc4_Vitiscan_GV.pdf

[![Démo Vitiscan](https://img.youtube.com/vi/wXaIMyCiRLs/hqdefault.jpg)](https://youtube.com/shorts/wXaIMyCiRLs)

*(clic sur la miniature pour voir la vidéo de démo)*

## Accès en production

| Composant | URL |
|---|---|
| `ui` (Streamlit Community Cloud) | https://project-final-vitiscan-rtugeymh3hyxpqvxwvbayh.streamlit.app/ |
| `api` (Render, diagnostic CNN) | https://vitiscan-api.onrender.com/docs |
| `rag-llm` (Render, plan de traitement) | https://vitiscan-rag-llm.onrender.com/docs |
| `rag-llm` - validation (Render) | https://vitiscan-rag-llm-validation.onrender.com/docs (interne, cible du DAG `dag_rag_ingestion` uniquement - jamais exposé à `ui/` ni aux utilisateurs finaux) |
| `labeling` (Streamlit Community Cloud) | https://project-final-vitiscan-2xgfzqjj4y7xj2oytrkfur.streamlit.app/ |

> Plan gratuit Render : 
> 
>les services `api`/`rag-llm` se mettent en veille après 15 min sans
> requête et peuvent prendre jusqu'à ~90-150s à répondre au premier appel qui suit (cf.
> `docs/deploiement-render-streamlit.md`).

## Structure du projet

```
api/        API FastAPI de prédiction CNN (charge le modèle depuis MLflow)
ui/         Interface Streamlit (upload photo -> diagnostic -> plan de traitement), un seul
            environnement prod (S3 + Neon réels)
labeling/   Dashboard Streamlit de labellisation humaine des photos soumises via ui/ (tri
            incoming/accepted/rejected, déplacement S3, calcul de drift modèle)
rag-llm/    API RAG-LLM (préconisation de traitement) + base de connaissances (data/knowledge/)
            + scripts d'ingestion + tests golden prompts (tests/) - 3 environnements
            (dev/validation/prod, cf. rag-llm/.env.template)
training/   Scripts d'entraînement du modèle CNN (train.py paramétrable), loggés dans MLflow
airflow/    Stack Airflow (Dockerfile, docker-compose.yml) pour l'orchestration
dags/       DAGs Airflow (ingestion RAG + porte de qualité golden prompts, test de plusieurs modèles CNN)
docs/       Documentation (audit nommage, suivi de refactoring, déploiement)
test_ui/    Scripts + photos annotées pour tester manuellement l'API de prédiction (EXIF GPS/date)
render.yaml Blueprint Render (déploiement api/ + rag-llm/, cf. docs/deploiement-render-streamlit.md)
work/       Fichiers de travail montés en volume dans Airflow (cache dataset, cache knowledge) -
            gitignoré, créé automatiquement au premier démarrage de la stack Airflow
link-env.sh Centralise les .env réels (non commités) dans ~/.vitiscan/ et les symlinke ici -
            à relancer dans tout nouveau worktree Git pour retrouver les mêmes configs
```

Chaque composant a son propre `requirements.txt` et `.env.template` (copier en `.env` et compléter en local,
jamais commité). Les fichiers réels sont centralisés dans `~/.vitiscan/` et symlinkés via
`./link-env.sh` (idempotent, à relancer dans chaque nouveau worktree).

MLflow est déployé séparément sur Hugging Face Spaces et n'est pas géré par ce dépôt.

## Nommage des maladies

Les 9 fiches de `rag-llm/data/knowledge/` utilisent un identifiant canonique unique (nom de fichier
= `id` = `cnn_label`) : le nom latin du taxon INRAE pour les 7 maladies du modèle en prod (ex.
`guignardia_bidwellii`), ou le nom de classe Kaggle tel quel pour les 2 maladies sans équivalent
INRAE (`brown_spot`, `shot_hole`).

## Démarrage rapide (local)

```bash
docker-compose up --build
```

> L'environnement de dev de référence pour ce projet n'a que `docker-compose` v1 (legacy, commande
> avec un tiret) — pas le plugin `docker compose` v2. Si votre machine a le plugin v2, `docker
> compose up --build` fonctionne aussi.

Services exposés : `api` (4000), `rag-llm` (9000), `ui` (8502), `labeling` (8503). `ui`/`labeling`
n'ont qu'un seul environnement (prod, S3 + Neon réels) ; `rag-llm` lit son `DATABASE_URL` (branche
Neon dev/validation/prod) directement depuis son propre `.env.*` - le service `postgres` local est
désactivé par défaut (conflit de nom de conteneur avec d'autres stacks). Voir `docker-compose.yml`
pour le détail.

## Tests

```bash
cd rag-llm && pip install -r requirements.txt -r requirements-test.txt
python -m app.ingestion          # ingère data/knowledge/ dans Postgres/pgvector (stack démarrée au préalable)
pytest tests/                    # golden prompts : vérifie retrieval + dosage + (si HF_API_TOKEN valide) diagnostic LLM
```

## Documentation

- [`docs/harmonisation-noms-maladies.md`](docs/harmonisation-noms-maladies.md) — audit et résolution du nommage des maladies
- [`docs/refactoring.md`](docs/refactoring.md) — suivi détaillé du refactoring CDSD -> ce dépôt
- [`docs/deploiement-render-streamlit.md`](docs/deploiement-render-streamlit.md) — déploiement en production (Render / Streamlit Community Cloud)
- [`labeling/README.md`](labeling/README.md) — dashboard de labellisation des photos (tri incoming/accepted/rejected, drift)
- [`ui/README.md`](ui/README.md) — interface Streamlit de diagnostic
