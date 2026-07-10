# rag-llm/ — Vitiscan Solutions API (RAG-LLM)

API FastAPI qui prend un diagnostic (label de maladie + mode de conduite + gravité + surface) et renvoie un
plan de traitement structuré : recherche RAG dans Postgres/pgvector (`app/vector_store.py`) + génération LLM
(Hugging Face Inference router, `app/llm_client.py`) + calcul de dosage déterministe (`app/dosage_rules.py`).

## Modèles utilisés

- LLM : Hugging Face Inference router, `meta-llama/Meta-Llama-3-8B-Instruct` par défaut (configurable via
  `HF_MODEL_ID`).
- Embeddings : `sentence-transformers/all-MiniLM-L6-v2` (local, calculé côté client).

## Structure

- `app/main.py` — API FastAPI (`POST /solutions`)
- `app/rag_pipeline.py` — orchestration retrieval + prompt + LLM + dosage
- `app/vector_store.py` — connexion Postgres/pgvector (Neon ou local) + recherche vectorielle
- `app/ingestion.py` — chargement des fiches markdown (`data/knowledge/`) et indexation dans Postgres/pgvector
  (`run_ingestion()`, réutilisable en CLI ou depuis un DAG Airflow)
- `db/schema.sql` — schéma SQL (table `vitiscan_knowledge`, index HNSW) exécuté de façon idempotente
- `app/dosage_rules.py` — règles de dosage déterministes par maladie/mode
- `app/diseases.py` — référentiel unique des labels/alias/traductions (évite la duplication qui existait
  entre `dosage_rules.py` et `rag_pipeline.py`)
- `app/prompts.py`, `app/llm_client.py`, `app/config.py`

## Base de connaissances

`data/knowledge/*.md` — fiches par maladie (front matter YAML + sections `# titre`). Volontairement light
pour l'instant (cf. specs.md).

## Local (sans Docker)

```bash
cp .env.template .env.dev   # puis compléter (HF_API_TOKEN au minimum). Même convention que
                            # Project_03_Fraud_Detection : .env.dev/.env.test/.env.prod,
                            # sélectionné par APP_ENV (défaut "dev"), cf. app/vector_store.py.
pip install -r requirements.txt

# Postgres/pgvector local pour dev :
docker-compose up -d postgres

# Ingestion des documents :
python -m app.ingestion

# Lancement de l'API :
uvicorn app.main:app --reload --port 9000
```

## Docker (contexte de build = rag-llm/, cf. render.yaml)

```bash
docker build -t vitiscan-rag-llm rag-llm/
docker run --env-file rag-llm/.env.dev -p 9000:9000 vitiscan-rag-llm
```

Voir le `docker-compose.yml` racine pour lancer l'ensemble de la stack (api + ui + rag-llm + postgres).

## Déploiement

Testable en local sous Docker, déployable ensuite sur Render (service Docker) — voir
`render.yaml` (racine) et `docs/deploiement-render-streamlit.md` pour la procédure complète.

## Neon (Postgres/pgvector) en production

Le plan gratuit Weaviate Cloud utilisé jusqu'ici était peu fiable (base détruite/indisponible après un
certain temps d'inactivité). Neon (Postgres managé, extension `pgvector`) résout nativement ce problème :
branches persistantes (pas de disque éphémère à gérer), gratuit, et joignable directement depuis Render
via `DATABASE_URL` — pas besoin de tunnel ni de dépendre d'une machine locale allumée, cf.
`docs/deploiement-render-streamlit.md`.
