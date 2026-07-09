# rag-llm/ — Vitiscan Solutions API (RAG-LLM)

API FastAPI qui prend un diagnostic (label de maladie + mode de conduite + gravité + surface) et renvoie un
plan de traitement structuré : recherche RAG dans Weaviate (`app/weaviate_client.py`) + génération LLM
(Hugging Face Inference router, `app/llm_client.py`) + calcul de dosage déterministe (`app/dosage_rules.py`).

## Modèles utilisés

- LLM : Hugging Face Inference router, `meta-llama/Meta-Llama-3-8B-Instruct` par défaut (configurable via
  `HF_MODEL_ID`).
- Embeddings : `sentence-transformers/all-MiniLM-L6-v2` (local, calculé côté client).

## Structure

- `app/main.py` — API FastAPI (`POST /solutions`)
- `app/rag_pipeline.py` — orchestration retrieval + prompt + LLM + dosage
- `app/weaviate_client.py` — connexion Weaviate (cloud ou local) + recherche vectorielle
- `app/ingestion.py` — chargement des fiches markdown (`data/knowledge/`) et indexation dans Weaviate
  (`run_ingestion()`, réutilisable en CLI ou depuis un DAG Airflow)
- `app/dosage_rules.py` — règles de dosage déterministes par maladie/mode
- `app/diseases.py` — référentiel unique des labels/alias/traductions (évite la duplication qui existait
  entre `dosage_rules.py` et `rag_pipeline.py`)
- `app/prompts.py`, `app/llm_client.py`, `app/config.py`

## Base de connaissances

`data/knowledge/*.md` — fiches par maladie (front matter YAML + sections `# titre`). Volontairement light
pour l'instant (cf. specs.md).

## Local (sans Docker)

```bash
cp .env.template .env   # puis compléter (HF_API_TOKEN au minimum)
pip install -r requirements.txt

# Weaviate local pour dev :
docker compose up -d weaviate

# Ingestion des documents :
python -m app.ingestion

# Lancement de l'API :
uvicorn app.main:app --reload --port 9000
```

## Docker (depuis la racine du dépôt)

```bash
docker build -f rag-llm/Dockerfile -t vitiscan-rag-llm .
docker run --env-file rag-llm/.env -p 9000:9000 vitiscan-rag-llm
```

Voir le `docker-compose.yml` racine pour lancer l'ensemble de la stack (api + ui + rag-llm + weaviate).

## Déploiement

Testable en local sous Docker, déployable ensuite sur Render (service Docker) — voir
`render.yaml` (racine) et `docs/deploiement-render-streamlit.md` pour la procédure complète.

## Weaviate en production

Le plan gratuit Weaviate Cloud utilisé jusqu'ici est peu fiable (base détruite/indisponible après un
certain temps d'inactivité). Dans un premier temps, Weaviate tourne en local sous Docker (voir NB dans
`specs.md`) ; une solution d'hébergement plus stable pour la prod reste à trancher — ne pas
l'auto-héberger sur Render en plan gratuit (disque éphémère + mise en veille, pire que Weaviate
Cloud gratuit), cf. `docs/deploiement-render-streamlit.md`.
