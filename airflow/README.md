# airflow/ — Stack Airflow 3.2.2 (Vitiscan)

Stack dédiée à Vitiscan, isolée de toute autre stack Airflow locale (cf. commentaire en tête de
`docker-compose.yml`). Sur le modèle du projet Fraud Detection, mais avec des noms de conteneurs,
une image Docker et un port hôte distincts pour ne jamais entrer en collision si les deux stacks
tournent en même temps sur la même machine.

## DAGs (voir `../dags/`)

- `dag_rag_ingestion` — détecte les nouveaux documents markdown dans
  `s3://RAG_S3_BUCKET/RAG_S3_PREFIX` (par défaut `s3-vitiscan-data/knowledge/current/`), les
  télécharge dans `work/rag-knowledge/` (cf. section "Répertoire de travail" ci-dessous) et les
  ingère dans un Weaviate de test (`weaviate-test`, propre à cette stack), rejoue les golden
  prompts (`rag-llm/tests/golden_prompts.yaml`) contre ce Weaviate de test comme porte de qualité,
  et seulement si tout est OK, ingère les documents dans le Weaviate de prod (celui du
  `docker-compose.yml` racine, rejoint via `host.docker.internal`).
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

## Pourquoi `host.docker.internal` pour joindre le Weaviate de prod ?

`airflow/docker-compose.yml` et le `docker-compose.yml` racine sont deux projets Compose
distincts (réseaux Docker séparés) : pas de résolution DNS par nom de service entre eux. Le plus
simple ici est de rejoindre le Weaviate de prod via son port publié sur l'hôte
(`host.docker.internal:8081`, cf. `extra_hosts` dans `docker-compose.yml`), plutôt que de
partager un réseau Docker externe entre les deux stacks.
