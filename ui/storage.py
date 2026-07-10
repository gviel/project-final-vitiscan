"""
Sauvegarde des photos soumises par les viticulteurs (S3) + de leurs métadonnées/prédiction
(Neon Postgres), pour labellisation humaine ultérieure et calcul de drift (cf. labeling/).

Module volontairement sans dépendance à streamlit (testable indépendamment de l'UI) - importé par
app.py et appelé uniquement après un diagnostic réussi.
"""
import hashlib
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import boto3
import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-west-3")
PHOTOS_S3_BUCKET = os.getenv("PHOTOS_S3_BUCKET", "s3-vitiscan-data")
PHOTOS_S3_PREFIX = os.getenv("PHOTOS_S3_PREFIX", "user-photos/")
DATABASE_URL = os.getenv("DATABASE_URL")

# Deux emplacements possibles pour labeling/db/schema.sql (source unique, pas de copie maintenue à
# la main) selon le mode de déploiement de ui/ :
# - image Docker (docker-compose local, éventuel futur déploiement Render) : copié au build dans
#   ./db/schema.sql (cf. ui/Dockerfile, `COPY labeling/db/schema.sql ./db/schema.sql`)
# - Streamlit Community Cloud : clone le dépôt entier (pas seulement ui/), donc le fichier est
#   directement accessible via son chemin relatif dans labeling/
_SCHEMA_SQL_CANDIDATES = [
    Path(__file__).resolve().parent / "db" / "schema.sql",
    Path(__file__).resolve().parents[1] / "labeling" / "db" / "schema.sql",
]


def _schema_sql_path() -> Path:
    for path in _SCHEMA_SQL_CANDIDATES:
        if path.exists():
            return path
    raise RuntimeError(
        "labeling/db/schema.sql introuvable (ni ui/db/schema.sql copié au build, ni dépôt cloné "
        "en entier) - cf. ui/Dockerfile et labeling/db/schema.sql."
    )


def _s3_client():
    return boto3.client("s3", region_name=AWS_DEFAULT_REGION)


@contextmanager
def db_client():
    """Même pattern que rag-llm/app/vector_store.py::db_client (connexion courte, pas de pool)."""
    database_url = (DATABASE_URL or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL n'est pas configuré - cf. ui/.env.template.")
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(conn) -> None:
    """Idempotent (CREATE TABLE/INDEX IF NOT EXISTS), même pattern que
    rag-llm/app/ingestion.py::ensure_schema - pas de système de migration versionné dans ce projet."""
    with conn.cursor() as cur:
        cur.execute(_schema_sql_path().read_text())
    conn.commit()


def compute_content_hash(file_bytes: bytes) -> str:
    """sha256 du contenu brut, utilisé pour la dédup visuelle dans labeling/ (pas une contrainte
    UNIQUE en base : deux photos identiques légitimes doivent pouvoir coexister)."""
    return hashlib.sha256(file_bytes).hexdigest()


def build_s3_key(content_hash: str, filename: str) -> str:
    """user-photos/YYYY/MM/DD/<hash>_<uuid>.<ext> - horodaté pour lister/paginer facilement par
    date dans labeling/, hash dans le nom pour un repérage visuel rapide des doublons."""
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    today = datetime.utcnow()
    return f"{PHOTOS_S3_PREFIX}{today:%Y/%m/%d}/{content_hash}_{uuid.uuid4().hex}{ext}"


def upload_photo_to_s3(file_bytes: bytes, s3_key: str) -> None:
    _s3_client().put_object(Bucket=PHOTOS_S3_BUCKET, Key=s3_key, Body=file_bytes)


def save_submission(
    file_bytes: bytes,
    filename: str,
    diagnostic: dict,
    gps_lat: Optional[float],
    gps_lon: Optional[float],
    exif_captured_at: Optional[str],
) -> Optional[int]:
    """
    Sauvegarde une soumission de diagnostic réussie : upload de la photo sur S3 + insertion des
    métadonnées (prédiction, GPS, model_version) dans Neon, pour labellisation humaine ultérieure
    (cf. labeling/) et calcul de drift.

    Ne lève jamais : un problème S3/Neon ne doit pas empêcher l'affichage du diagnostic déjà
    obtenu par le viticulteur (cf. ui/app.py, appelant). Retourne l'id de la ligne insérée, ou None
    en cas d'échec (loggé via logger.exception).
    """
    try:
        predictions = diagnostic.get("predictions") or []
        if not predictions:
            return None
        best = predictions[0]

        content_hash = compute_content_hash(file_bytes)
        s3_key = build_s3_key(content_hash, filename)

        # Upload S3 avant l'insert DB : en cas d'échec de l'insert après un upload réussi, la
        # photo reste orpheline sur S3 (sans ligne Neon) - accepté pour ce MVP, pas de logique de
        # nettoyage/rollback S3 (cas rare, sans impact utilisateur, nettoyable manuellement).
        upload_photo_to_s3(file_bytes, s3_key)

        with db_client() as conn:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vitiscan_photos (
                        s3_bucket, s3_key, content_hash, exif_captured_at, gps_lat, gps_lon,
                        predicted_label, confidence, raw_predictions, model_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        PHOTOS_S3_BUCKET,
                        s3_key,
                        content_hash,
                        exif_captured_at,
                        gps_lat,
                        gps_lon,
                        best.get("disease"),
                        best.get("confidence"),
                        Jsonb(predictions),
                        diagnostic.get("model_version"),
                    ),
                )
                photo_id = cur.fetchone()[0]
            conn.commit()
        return photo_id
    except Exception:
        logger.exception("Échec de la sauvegarde photo+métadonnées (S3/Neon)")
        return None
