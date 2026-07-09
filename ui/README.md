# ui/ — Vitiscan Streamlit UI

Interface Streamlit pour le viticulteur : upload d'une photo de feuille de vigne, appel à l'API de
prédiction (`api/`) pour le diagnostic, puis à l'API RAG-LLM (`rag-llm/`) pour un plan de traitement.

## Local (sans Docker)

```bash
cp .env.template .env   # puis compléter
pip install -r requirements.txt
streamlit run app.py
```

## Docker (depuis la racine du dépôt)

```bash
docker build -f ui/Dockerfile -t vitiscan-ui .
docker run --env-file ui/.env -p 8501:8501 vitiscan-ui
```

Voir le `docker-compose.yml` racine pour lancer l'ensemble de la stack.

## Déploiement

Testable en local sous Docker, déployable ensuite sur Streamlit Community Cloud — voir
`docs/deploiement-render-streamlit.md` pour la procédure complète (secrets, vérification).
