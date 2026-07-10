# airflow/ — Stack Airflow 3.2.2 (Vitiscan)

Stack dédiée à Vitiscan, isolée de toute autre stack Airflow locale (cf. commentaire en tête de
`docker-compose.yml`). Sur le modèle du projet Fraud Detection, mais avec des noms de conteneurs,
une image Docker et un port hôte distincts pour ne jamais entrer en collision si les deux stacks
tournent en même temps sur la même machine.

## DAGs (voir `../dags/`)

- `dag_rag_ingestion` — détecte les nouveaux documents markdown dans
  `s3://RAG_S3_BUCKET/RAG_S3_PREFIX` (par défaut `s3-vitiscan-data/knowledge/current/`), les
  télécharge dans `work/rag-knowledge/` (cf. section "Répertoire de travail" ci-dessous) et les
  ingère dans la branche Neon (Postgres/pgvector) de test (`DATABASE_URL_TEST`), rejoue les golden
  prompts (`rag-llm/tests/golden_prompts.yaml`) contre cette branche de test comme porte de
  qualité, et seulement si tout est OK, ingère les documents dans la branche Neon de prod
  (`DATABASE_URL_PROD`, celle utilisée par `rag-llm/` en production).
- `dag_train_model` — sweep multi-modèles CNN : lit `../training/config.yml::models_to_run`
  (monté en lecture seule) et lance un `train.py` en subprocess par modèle (une tâche Airflow par
  modèle, exécution séquentielle). Déclenchement manuel uniquement (`schedule=None`). Dataset
  téléchargé une seule fois dans `work/training-data/` (cf. ci-dessous, persistant entre runs, pas
  re-téléchargé). Param `limit_batches` (optionnel) pour un sweep smoke-test rapide.

## Répertoire de travail (`work/`, racine du dépôt)

Bind-mount unique (`../work:/opt/airflow/work`, `WORK_DIR` dans `dags/config.py`) pour tous les
fichiers de travail volumineux ou coûteux à retélécharger, plutôt qu'un volume Docker nommé opaque
— visible/inspectable directement depuis l'hôte, persistant entre recréations de conteneur :
- `work/training-data/` — cache du dataset CNN (`dataset_inrae.zip` + extraction), téléchargé une
  seule fois par `dag_train_model` (cf. `training/data_utils.py::prepare_dataset`).
- `work/rag-knowledge/` — cache de téléchargement des documents markdown S3 pour
  `dag_rag_ingestion`, vidé et réécrit à chaque run (pas de purge manuelle à faire après coup,
  contrairement à l'ancien `tempfile.mkdtemp()`).

Gitignoré (`work/` à la racine du `.gitignore` du dépôt) — jamais committé.

## Démarrage

```bash
cp .env.template .env   # puis compléter (bucket S3, credentials AWS)
./start.sh
```

UI Airflow : http://localhost:8090 (airflow / airflow)

```bash
./stop.sh
```

## Pourquoi 2 branches Neon plutôt que 2 instances Weaviate ?

`airflow/docker-compose.yml` et le `docker-compose.yml` racine sont deux projets Compose
distincts (réseaux Docker séparés) : pas de résolution DNS par nom de service entre eux. Avant la
migration pgvector, le DAG rejoignait le Weaviate "prod" du `docker-compose.yml` racine via son
port publié sur l'hôte (`host.docker.internal`). Neon est joignable directement par
`DATABASE_URL_TEST`/`DATABASE_URL_PROD` (2 branches Neon créées manuellement au préalable,
branching natif Neon), donc plus besoin de `host.docker.internal` ni de partager un réseau Docker
externe entre les deux stacks.
