"""
Tâches du DAG dag_retrain_from_labeled_photos (specs.md, partie "Faire évoluer pour l'AIA") :
- détecte les photos acceptées via labeling/ (table Neon vitiscan_photos, cf.
  labeling/db/schema.sql) pas encore intégrées au dataset d'entraînement CNN
- les copie dans organized_data_inrae/train/<human_label>/ (uniquement train/ - val/test restent
  fixes depuis le split initial, cf. training/data_utils.py::_prepare_inrae_dataset)
- déclenche dag_train_model (TriggerDagRunOperator, cf. dags/dag_retrain_from_labeled_photos.py)

Même base Neon "prod" que rag-llm (DATABASE_URL_PROD), table différente (vitiscan_photos, pas de
FK/dépendance avec vitiscan_knowledge). Même bucket S3 que RAG_S3_BUCKET/TRAINING_S3_BUCKET
(s3-vitiscan-data), préfixe différent (PHOTOS_S3_PREFIX).
"""
import logging
from pathlib import Path

import boto3
import psycopg

from config import AWS_DEFAULT_REGION, DATABASE_URL_PROD, LABELING_DIR, TRAINING_DATA_DIR

logger = logging.getLogger(__name__)

# Même layout que training/data_utils.py::dataset_root_dir("inrae", ...) - dupliqué ici plutôt que
# d'importer training/ (dépendances ML non installées pour cette tâche, cf. dags/tasks/train_model.py
# qui lance train.py en subprocess plutôt qu'en import direct, pour la même raison d'isolation).
ORGANIZED_DATA_DIR = TRAINING_DATA_DIR / "data-inrae" / "organized_data_inrae"

PHOTOS_SCHEMA_SQL_PATH = LABELING_DIR / "db" / "schema.sql"


def _s3_client():
    return boto3.client("s3", region_name=AWS_DEFAULT_REGION)


def _ensure_photos_schema(conn) -> None:
    conn.execute(PHOTOS_SCHEMA_SQL_PATH.read_text())
    conn.commit()


def branch_check_new_labels(**context) -> str:
    """
    Vérifie que le dataset de base a déjà été construit (précondition : au moins un run manuel de
    dag_train_model, cf. plan) puis cherche les photos accept_photo (labeling/) pas encore copiées
    dans le dataset. Retourne le prochain task_id ("add_to_dataset" ou "stop_dag").
    """
    if not (ORGANIZED_DATA_DIR / "train").is_dir() or not (ORGANIZED_DATA_DIR / "val").is_dir() \
            or not (ORGANIZED_DATA_DIR / "test").is_dir():
        logger.warning(
            f"[photo_retraining] {ORGANIZED_DATA_DIR} incomplet (train/val/test) - lancer d'abord "
            "un run manuel de dag_train_model pour construire le dataset de base."
        )
        return "stop_dag"

    with psycopg.connect(DATABASE_URL_PROD) as conn:
        _ensure_photos_schema(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, s3_bucket, s3_key, human_label
                FROM vitiscan_photos
                WHERE status = 'accepted' AND human_label IS NOT NULL AND training_included_at IS NULL
                ORDER BY id
            """)
            rows = cur.fetchall()

    if not rows:
        logger.info("[photo_retraining] Aucune nouvelle photo labellisée à intégrer.")
        return "stop_dag"

    photos = [
        {"id": r[0], "s3_bucket": r[1], "s3_key": r[2], "human_label": r[3]}
        for r in rows
    ]
    logger.info(f"[photo_retraining] {len(photos)} photo(s) acceptée(s) à intégrer : {[p['id'] for p in photos]}")
    context["ti"].xcom_push(key="photos", value=photos)
    return "add_to_dataset"


def add_to_dataset(**context) -> None:
    """
    Télécharge chaque photo listée par branch_check_new_labels et l'écrit dans
    organized_data_inrae/train/<human_label>/photo_<id><ext>, puis marque chaque ligne comme
    intégrée (training_included_at). Idempotent : un re-run recopie le même fichier au même chemin
    (sans effet) et ne remet à jour que les lignes réellement traitées.
    """
    photos = context["ti"].xcom_pull(task_ids="branch_check_new_labels", key="photos")
    client = _s3_client()
    included_ids = []

    for photo in photos:
        ext = Path(photo["s3_key"]).suffix or ".jpg"
        dest_dir = ORGANIZED_DATA_DIR / "train" / photo["human_label"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"photo_{photo['id']}{ext}"
        client.download_file(photo["s3_bucket"], photo["s3_key"], str(dest_path))
        included_ids.append(photo["id"])
        logger.info(f"[photo_retraining] photo {photo['id']} -> {dest_path}")

    with psycopg.connect(DATABASE_URL_PROD) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vitiscan_photos SET training_included_at = now() WHERE id = ANY(%s)",
                (included_ids,),
            )
        conn.commit()

    logger.info(f"[photo_retraining] {len(included_ids)} photo(s) intégrée(s) au dataset d'entraînement.")
