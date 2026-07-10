"""
Accès Neon Postgres pour le dashboard de labeling : lecture/filtrage des photos soumises via
ui/storage.py, assignation d'un label humain, calcul du drift (accord prédiction/label humain).

Module volontairement sans dépendance à streamlit (testable indépendamment) - importé par app.py.
"""
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-west-3")
PHOTOS_S3_BUCKET = os.getenv("PHOTOS_S3_BUCKET", "s3-vitiscan-data")
DATABASE_URL = os.getenv("DATABASE_URL")

# labeling/db/schema.sql : source unique du schéma (cf. ui/storage.py qui référence ce même
# fichier, soit copié au build Docker, soit via le dépôt cloné en entier sur Streamlit Cloud).
SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "db" / "schema.sql"

_DISTINCT_ALLOWED_COLUMNS = {"model_version", "predicted_label"}


def _s3_client():
    return boto3.client("s3", region_name=AWS_DEFAULT_REGION)


@contextmanager
def db_client():
    """Même pattern que rag-llm/app/vector_store.py::db_client (connexion courte, pas de pool)."""
    database_url = (DATABASE_URL or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL n'est pas configuré - cf. labeling/.env.template.")
    conn = psycopg.connect(database_url)
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(conn) -> None:
    """Idempotent (CREATE TABLE/INDEX IF NOT EXISTS), même pattern que
    rag-llm/app/ingestion.py::ensure_schema - pas de système de migration versionné dans ce projet."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL_PATH.read_text())
    conn.commit()


def list_distinct(conn, column: str) -> List[str]:
    """Valeurs distinctes non nulles d'une colonne, pour peupler les dropdowns de filtre.
    `column` doit être dans _DISTINCT_ALLOWED_COLUMNS (whitelist, la colonne est interpolée dans
    le SQL car les identifiants de colonne ne sont pas paramétrables avec psycopg)."""
    if column not in _DISTINCT_ALLOWED_COLUMNS:
        raise ValueError(f"Colonne non autorisée: {column!r}")
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {column} FROM vitiscan_photos WHERE {column} IS NOT NULL ORDER BY {column}")
        return [row[0] for row in cur.fetchall()]


def list_photos(
    conn,
    model_version: Optional[str] = None,
    predicted_label: Optional[str] = None,
    labeled_status: str = "all",
    only_duplicates: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retourne (rows, total_count) pour pagination. Chaque row inclut `duplicate_count` (nombre de
    photos partageant le même content_hash, >1 si doublon). labeled_status: "all" | "labeled" |
    "unlabeled". only_duplicates filtre sur les content_hash apparaissant plus d'une fois.
    """
    conditions = []
    params: Dict[str, Any] = {}

    if model_version:
        conditions.append("p.model_version = %(model_version)s")
        params["model_version"] = model_version
    if predicted_label:
        conditions.append("p.predicted_label = %(predicted_label)s")
        params["predicted_label"] = predicted_label
    if labeled_status == "labeled":
        conditions.append("p.human_label IS NOT NULL")
    elif labeled_status == "unlabeled":
        conditions.append("p.human_label IS NULL")
    if only_duplicates:
        conditions.append(
            "p.content_hash IN (SELECT content_hash FROM vitiscan_photos GROUP BY content_hash HAVING COUNT(*) > 1)"
        )

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM vitiscan_photos p {where_clause}", params)
        total = cur.fetchone()["n"]

        page_params = dict(params)
        page_params["limit"] = page_size
        page_params["offset"] = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT p.*,
                   (SELECT COUNT(*) FROM vitiscan_photos p2 WHERE p2.content_hash = p.content_hash) AS duplicate_count
            FROM vitiscan_photos p
            {where_clause}
            ORDER BY p.submitted_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            page_params,
        )
        rows = cur.fetchall()

    return rows, total


def get_photo(conn, photo_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM vitiscan_photos WHERE id = %s", (photo_id,))
        return cur.fetchone()


def set_human_label(conn, photo_id: int, human_label: str, labeled_by: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE vitiscan_photos SET human_label = %s, labeled_at = now(), labeled_by = %s WHERE id = %s",
            (human_label, labeled_by, photo_id),
        )
    conn.commit()


def compute_drift_metrics(conn, model_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Parmi les photos labellisées (human_label IS NOT NULL) : taux d'accord global
    (predicted_label = human_label) + ventilation par model_version.
    """
    where_clause = "WHERE human_label IS NOT NULL"
    params: Dict[str, Any] = {}
    if model_version:
        where_clause += " AND model_version = %(model_version)s"
        params["model_version"] = model_version

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT model_version,
                   COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE predicted_label = human_label) AS n_agree
            FROM vitiscan_photos
            {where_clause}
            GROUP BY model_version
            ORDER BY model_version
            """,
            params,
        )
        by_version = cur.fetchall()

    n_total = sum(row["n"] for row in by_version)
    n_agree_total = sum(row["n_agree"] for row in by_version)

    return {
        "n_labeled": n_total,
        "global_agreement": (n_agree_total / n_total) if n_total else None,
        "by_model_version": [
            {
                "model_version": row["model_version"],
                "n": row["n"],
                "agreement": (row["n_agree"] / row["n"]) if row["n"] else None,
            }
            for row in by_version
        ],
    }


def presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    """URL de prévisualisation temporaire, sans rendre le bucket public."""
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": PHOTOS_S3_BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
    )
