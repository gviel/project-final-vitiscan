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
# Doit avoir la même valeur que ui/.env.template (PHOTOS_S3_PREFIX) : sert à localiser l'objet S3
# actuel d'une photo pour la déplacer lors d'un changement de statut (cf. _replace_status).
PHOTOS_S3_PREFIX = os.getenv("PHOTOS_S3_PREFIX", "user-photos/")
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
        result = [row[0] for row in cur.fetchall()]
    # Referme la transaction implicite tout de suite (psycopg3 n'est pas en autocommit) : sinon
    # elle reste ouverte ("idle in transaction") jusqu'au prochain commit/rollback/close, ce qui
    # peut faire attendre le verrou ACCESS EXCLUSIVE que labeling/db.py::ensure_schema (ou
    # ui/storage.py::ensure_schema, appelé à chaque upload) doit prendre pour son ALTER TABLE -
    # constaté en testant l'enchaînement complet (blocage indéfini dans un même process de test).
    conn.commit()
    return result


def list_photos(
    conn,
    model_version: Optional[str] = None,
    predicted_label: Optional[str] = None,
    status: Optional[str] = None,
    only_duplicates: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Retourne (rows, total_count) pour pagination. Chaque row inclut `duplicate_count` (nombre de
    photos partageant le même content_hash, >1 si doublon). status: None = tous, sinon "incoming" |
    "accepted" | "rejected". only_duplicates filtre sur les content_hash apparaissant plus d'une fois.
    """
    conditions = []
    params: Dict[str, Any] = {}

    if model_version:
        conditions.append("p.model_version = %(model_version)s")
        params["model_version"] = model_version
    if predicted_label:
        conditions.append("p.predicted_label = %(predicted_label)s")
        params["predicted_label"] = predicted_label
    if status:
        conditions.append("p.status = %(status)s")
        params["status"] = status
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

    conn.commit()  # cf. list_distinct : referme la transaction implicite, ne pas la laisser ouverte
    return rows, total


def get_photo(conn, photo_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM vitiscan_photos WHERE id = %s", (photo_id,))
        row = cur.fetchone()
    conn.commit()  # cf. list_distinct : referme la transaction implicite, ne pas la laisser ouverte
    return row


def _replace_status(s3_key: str, new_status: str) -> str:
    """PREFIX/<status>/reste... -> PREFIX/<new_status>/reste... (cf. ui/storage.py::build_s3_key
    pour le layout complet)."""
    rest = s3_key[len(PHOTOS_S3_PREFIX):]
    _, _, tail = rest.partition("/")
    return f"{PHOTOS_S3_PREFIX}{new_status}/{tail}"


def _move_s3_object(old_key: str, new_key: str) -> None:
    """S3 n'a pas de "move" atomique : copy puis delete."""
    client = _s3_client()
    client.copy_object(
        Bucket=PHOTOS_S3_BUCKET,
        CopySource={"Bucket": PHOTOS_S3_BUCKET, "Key": old_key},
        Key=new_key,
    )
    client.delete_object(Bucket=PHOTOS_S3_BUCKET, Key=old_key)


def _finalize(conn, photo_id: int, new_status: str, human_label: Optional[str], labeled_by: str) -> None:
    """Fonction interne partagée par accept_photo/reject_photo : déplace l'objet S3 vers le
    nouveau statut puis met à jour la ligne. Peut lever (S3/DB indisponible) - contrairement à
    ui/storage.py::save_submission, ce module ne masque pas les erreurs : c'est un outil interne où
    voir l'erreur réelle est utile (cf. labeling/app.py, qui les affiche via st.error)."""
    photo = get_photo(conn, photo_id)
    if photo is None:
        raise ValueError(f"Photo {photo_id} introuvable")

    new_key = _replace_status(photo["s3_key"], new_status)
    _move_s3_object(photo["s3_key"], new_key)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE vitiscan_photos
            SET status = %s, s3_key = %s, human_label = %s, labeled_at = now(), labeled_by = %s
            WHERE id = %s
            """,
            (new_status, new_key, human_label, labeled_by, photo_id),
        )
    conn.commit()


def accept_photo(conn, photo_id: int, human_label: str, labeled_by: str) -> None:
    """incoming -> accepted : la photo entre dans le dataset avec un label confirmé (obligatoire)."""
    _finalize(conn, photo_id, "accepted", human_label, labeled_by)


def reject_photo(conn, photo_id: int, labeled_by: str, human_label: Optional[str] = None) -> None:
    """incoming -> rejected : label optionnel (une photo peut être rejetée sans label, ex. photo
    inexploitable)."""
    _finalize(conn, photo_id, "rejected", human_label, labeled_by)


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
    conn.commit()  # cf. list_distinct : referme la transaction implicite, ne pas la laisser ouverte

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
