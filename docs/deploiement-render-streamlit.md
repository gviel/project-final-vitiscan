# Déploiement — Render (`api`, `rag-llm`) + Streamlit Community Cloud (`ui`)

Étape 9 du TODO Partie 1 (`specs.md`). Couvre le premier déploiement et les mises à jour
ultérieures. MLflow reste hors scope (déjà déployé sur Hugging Face Spaces, cf. `specs.md`).

## Vue d'ensemble

| Composant | Plateforme | Comment |
|---|---|---|
| `api/` (prédiction CNN) | Render, service Docker | `render.yaml` (Blueprint) |
| `rag-llm/` (RAG-LLM) | Render, service Docker | `render.yaml` (Blueprint) |
| `ui/` (Streamlit) | Streamlit Community Cloud | connexion directe au dépôt GitHub |
| Base de connaissances RAG | Neon (Postgres + `pgvector`) | externe, `DATABASE_URL` sur `vitiscan-rag-llm`, cf. ci-dessous |
| MLflow | Hugging Face Spaces (existant) | rien à faire |

Un `render.yaml` à la racine du dépôt déclare `api` et `rag-llm` comme Blueprint Render
(Infrastructure as Code) — un seul clic pour créer les deux services avec la bonne config
(`dockerfilePath`, `healthCheckPath`, variables d'environnement). `ui/` n'a pas sa place dans ce
fichier : Streamlit Community Cloud ne consomme pas `render.yaml`, il déploie directement depuis
`ui/app.py` par sa propre interface.

## URLs déployées (test/prod)

| Service | URL | Latence à froid (veille) | Latence à chaud |
|---|---|---|---|
| `vitiscan-api` (Render) | https://vitiscan-api.onrender.com | ~150s (recharge du modèle CNN depuis MLflow, torch+mlflow) | ~0.6s |
| `vitiscan-rag-llm` (Render) | https://vitiscan-rag-llm.onrender.com | non mesuré à froid (déjà chaud lors du 1er test) | ~0.6s |
| Neon (Postgres/pgvector, branche prod) | interne (`DATABASE_URL`, non exposée publiquement) | — | — |
| `ui` (Streamlit Community Cloud) | https://project-final-vitiscan-rtugeymh3hyxpqvxwvbayh.streamlit.app/ | — | — |

**Mise en veille Render (plan free)** : après **15 minutes** sans requête entrante (confirmé
[render.com/docs/free](https://render.com/docs/free)), le service se met en veille. La requête
suivante le réveille automatiquement, avec la latence à froid indiquée ci-dessus.

## Historique — Blocage ngrok TCP (gRPC), pertinent avant la migration pgvector

> Cette section documente un problème résolu par la migration vers Neon/pgvector (le tunnel ngrok
> n'est plus utilisé, cf. `docs/simulation-prod-ngrok.md`). Conservée pour référence historique.

Le tunnel TCP ngrok (nécessaire pour le gRPC de Weaviate, cf. `docs/simulation-prod-ngrok.md`) se
créait sans erreur côté agent local, mais **ne routait pas réellement le trafic externe** :
connexion refusée aussi bien en local qu'depuis Render, alors que l'IP de l'edge ngrok répondait
normalement sur le port 443. Cause exacte non confirmée (limitation du plan gratuit non documentée
clairement, délai de propagation de la vérification carte, ou autre). Conséquence : `/solutions`
sur `vitiscan-rag-llm` renvoyait une erreur 500 tant que ce point n'était pas résolu — `/health`
fonctionnait normalement (ne dépendait pas de Weaviate).

## Pourquoi la base de connaissances RAG est sur Neon (pas sur Render)

`rag-llm/README.md` documentait que le plan gratuit Weaviate Cloud utilisé pour la CDSD était peu
fiable (base détruite après un certain temps d'inactivité), et que l'auto-héberger sur Render en
plan gratuit aurait été **pire** : les services Docker gratuits de Render n'ont pas de disque
persistant et se mettent en veille après 15 min d'inactivité (cf. plus bas), donc les données
auraient été perdues à chaque redémarrage, pas seulement après une longue inactivité.

Neon (Postgres managé, extension `pgvector`) résout nativement ce problème : persistant (pas de
disque éphémère), gratuit, et joignable directement depuis Render via `DATABASE_URL` — pas besoin
de tunnel (ngrok) ni de dépendre d'une machine locale allumée. Une seule variable à renseigner sur
`vitiscan-rag-llm` : `DATABASE_URL` (branche Neon "prod", URL pooled).

Tant que cette variable n'est pas renseignée, `rag-llm` peut être déployé et fonctionner (health
check OK), mais `/solutions` tombera sur le message de repli générique si la base ne pointe vers
rien d'ingéré (cf. `docs/harmonisation-noms-maladies.md` pour ce comportement).

## 1. `api/` sur Render

### Via Blueprint (recommandé)

1. Render Dashboard -> **New** -> **Blueprint** -> sélectionner ce dépôt GitHub.
2. Render détecte `render.yaml` à la racine et propose de créer `vitiscan-api` +
   `vitiscan-rag-llm`.
3. Renseigner les variables marquées `sync: false` quand demandé (une seule fois, à la création) :
   `MLFLOW_MODEL_ID`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (mêmes valeurs que
   `api/.env`, cf. `api/.env.template`).
4. Déployer. Le build utilise `dockerfilePath: api/Dockerfile` avec un contexte de build = racine
   du dépôt (défaut Render), cohérent avec `docker-compose.yml` (`context: .`,
   `dockerfile: api/Dockerfile`) — pas besoin d'un `dockerContext` différent.

### Vérification post-déploiement

```bash
curl https://<votre-service>.onrender.com/health
# {"status":"ok","model_loaded":true,"model_version":"..."}
curl https://<votre-service>.onrender.com/diseases
# {"diseases":{"colomerus_vitis":"Erinose",...},"dataset_name":"inrae"}
curl -X POST https://<votre-service>.onrender.com/diagno -F "file=@photo.jpg"
```

## 2. `rag-llm/` sur Render

Créé automatiquement par le même Blueprint (`vitiscan-rag-llm`). Renseigner à la création :
`HF_API_TOKEN` (cf. `rag-llm/.env.template`), `DATABASE_URL` (branche Neon "prod", cf. section
ci-dessus).

**Ingestion des documents** : contrairement à `docker-compose` en local (où `python -m
app.ingestion` se lance manuellement), rien n'ingère automatiquement les fiches
`data/knowledge/*.md` dans la base de prod au déploiement. Deux options :
- lancer `python -m app.ingestion` une fois manuellement, en pointant `DATABASE_URL` vers la
  branche Neon de prod ;
- ou attendre que le DAG Airflow `dag_rag_ingestion` soit opérationnel de bout en bout (cf.
  `docs/refactoring.md`, reste à faire) — c'est son rôle prévu.

### Vérification post-déploiement

```bash
curl https://<votre-service>.onrender.com/health
curl -X POST https://<votre-service>.onrender.com/solutions \
  -H "Content-Type: application/json" \
  -d '{"cnn_label":"guignardia_bidwellii","mode":"conventionnel","severity":"forte","area_m2":5000}'
# treatment_plan doit être non vide et diagnostic ne doit PAS contenir
# "Les informations disponibles sur cette maladie sont insuffisantes"
```

## 3. `ui/` sur Streamlit Community Cloud

1. [share.streamlit.io](https://share.streamlit.io) -> **New app** -> sélectionner ce dépôt
   GitHub, branche, et **Main file path** = `ui/app.py`.
2. Streamlit Cloud détecte automatiquement `ui/requirements.txt` (même dossier que `app.py`).
3. **Secrets** (menu de l'app -> *Settings* -> *Secrets*) : coller au format TOML, valeurs
   **au premier niveau** (pas dans une table `[section]`) pour qu'elles soient aussi exposées comme
   variables d'environnement classiques (`os.getenv`, utilisé par `ui/app.py` — pas de `st.secrets`
   dans le code actuel) :
   ```toml
   API_DIAGNO = "https://<votre-service-api>.onrender.com"
   API_SOLUTIONS = "https://<votre-service-rag-llm>.onrender.com"
   MOCK = "0"
   DEBUG = "0"
   ```
4. Le thème (`ui/.streamlit/config.toml`, vert agriculture) est repris automatiquement — pas de
   configuration supplémentaire côté Streamlit Cloud.

### Vérification post-déploiement

Ouvrir l'URL `https://<app>.streamlit.app`, uploader une photo de feuille de vigne, vérifier que
le diagnostic et le plan de traitement s'affichent (bout en bout à travers les 2 services Render).

## Mise à jour (redeploy)

- `api`/`rag-llm` (Render) : tout push sur la branche connectée redéploie automatiquement (comportement
  par défaut Render pour un service Git-connecté). Un changement de variable d'environnement
  redéploie aussi automatiquement.
- `ui` (Streamlit Cloud) : idem, redeploy automatique sur push. Changement de secrets -> redémarrage
  de l'app (pas de rebuild, juste un restart).

## Limites connues du plan gratuit Render

Un service Docker gratuit se met en veille après **15 minutes** sans requête entrante, et met
jusqu'à **~1 minute** à redémarrer à la requête suivante (source :
[render.com/docs/free](https://render.com/docs/free)). Concrètement pour ce projet :
- `api` doit recharger le modèle CNN depuis MLflow au réveil (torch + mlflow, plusieurs secondes).
- `rag-llm` doit recharger `sentence-transformers` au réveil.
- Un premier appel après veille peut donc prendre 30 à 90 secondes avant de répondre — attendu,
  pas un bug. Passer en plan payant (à partir de 7 $/mois) supprime la mise en veille.

## Fichiers concernés

- `render.yaml` (racine) — Blueprint Render pour `api` + `rag-llm`.
- `api/Dockerfile`, `rag-llm/Dockerfile` — `CMD` modifié pour lire `$PORT` si fourni par la
  plateforme d'hébergement (sinon 4000/9000 par défaut, comportement local inchangé) : Render
  n'est pas garanti de détecter automatiquement un port fixé en dur dans l'image.
