# api/ — Vitiscan Diagno API

API FastAPI de prédiction de maladie de la vigne à partir d'une photo de feuille. Charge le modèle CNN
depuis MLflow (`models:/<MLFLOW_MODEL_ID>`) au démarrage.

## Endpoints

- `GET /` — statut basique
- `GET /health` — statut + modèle chargé ou non
- `GET /diseases` — liste des maladies connues du modèle courant
- `POST /diagno` — upload d'une image (`multipart/form-data`, champ `file`) → prédictions triées par confiance

## Local (sans Docker)

```bash
cp .env.template .env   # puis compléter
pip install -r requirements.txt
python app.py
```

## Docker (contexte de build = api/, cf. render.yaml)

```bash
docker build -t vitiscan-api api/
docker run --env-file api/.env -p 4000:4000 vitiscan-api
```

Voir le `docker-compose.yml` racine pour lancer l'ensemble de la stack.

## Déploiement

Testable en local sous Docker, déployable ensuite sur Render (service Docker) — voir
`render.yaml` (racine) et `docs/deploiement-render-streamlit.md` pour la procédure complète.
