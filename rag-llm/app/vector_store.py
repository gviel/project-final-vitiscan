import os
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = "vitiscan_knowledge"

# ---------- Embedder global ----------

_EMBEDDER: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    """Retourne un modèle SentenceTransformer (chargé une seule fois)."""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _EMBEDDER


# ---------- Client Postgres/pgvector (context manager) ----------

@contextmanager
def db_client():
    """
    2 modes de connexion, dans cet ordre de priorité :
    1. DATABASE_URL défini (Neon - branche test/prod/dev, ou toute URL postgresql://... complète)
       -> utilisé tel quel. Privilégier l'URL "pooled" fournie par Neon (hôte suffixé -pooler),
       ce module ouvrant une connexion courte par requête HTTP.
    2. Sinon -> connexion locale via PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE (alignée sur le
       service postgres du docker-compose local).
    """
    database_url = (os.getenv("DATABASE_URL") or "").strip()

    if not database_url and (os.getenv("HF_SPACE_ID") or os.getenv("SPACE_ID") or os.getenv("K_SERVICE")):
        raise RuntimeError("DATABASE_URL n'est pas configuré en environnement déployé.")

    if database_url:
        conn = psycopg.connect(database_url)
    else:
        conn = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5433")),
            user=os.getenv("PGUSER", "vitiscan"),
            password=os.getenv("PGPASSWORD", "vitiscan"),
            dbname=os.getenv("PGDATABASE", "vitiscan_knowledge"),
        )
    register_vector(conn)

    try:
        yield conn
    finally:
        conn.close()


# ---------- Recherche de chunks de traitement ----------

def search_treatment_chunks(
    client,
    disease_input: str,
    mode: Optional[str],
    severity: Optional[str],
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """
    Retrieval RAG robuste (même comportement que l'ancienne implémentation Weaviate) :
    - accepte disease_input au format canonique (ex: "plasmopara_viticola") ou alias court hérité
    - filtre par (cnn_label == ...) OR (disease_id == ...) — les deux propriétés portent
      désormais la même valeur canonique dans le frontmatter des fiches, donc pas besoin de
      deviner laquelle des deux le disease_input représente
    - filtre mode_conduite si fourni (recouvrement de tableau), sinon pas de filtre mode
    - fallback : si 0 résultat avec mode -> relance sans mode
    """
    key = (disease_input or "").strip()
    if not key:
        return []

    query_text = (
        f"Recommandations de traitement vigne pour {key}. "
        f"Mode: {mode or 'non spécifié'}. Gravité: {severity or 'non spécifiée'}. "
        "Inclure diagnostic, actions curatives, prévention, et précautions."
    )

    embedder = get_embedder()
    query_vector = embedder.encode(query_text).tolist()

    def run_query(with_mode: bool) -> List[Dict[str, Any]]:
        mode_clause = "AND mode_conduite && %(mode)s" if (with_mode and mode) else ""
        # ::vector explicite sur %(qv)s : sans lui, Postgres reçoit le paramètre comme un
        # double precision[] non typé et l'opérateur <=> devient ambigu entre vector/halfvec/
        # sparsevec ("operator does not exist: vector <=> double precision[]"), confirmé en test
        # contre Neon. && sur mode_conduite (TEXT[]) n'a pas ce problème, pas besoin de cast là.
        sql = f"""
            SELECT text, section, disease_id, cnn_label, nom_fr, mode_conduite,
                   embedding <=> %(qv)s::vector AS distance
            FROM {TABLE_NAME}
            WHERE (cnn_label = %(key)s OR disease_id = %(key)s)
            {mode_clause}
            ORDER BY embedding <=> %(qv)s::vector
            LIMIT %(top_k)s
        """
        params: Dict[str, Any] = {"qv": query_vector, "key": key, "top_k": top_k}
        if with_mode and mode:
            params["mode"] = [mode]

        try:
            with client.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        except Exception as e:
            print(f"[RAG] Erreur requête pgvector: {e}")
            # Sans rollback, la transaction implicite resterait "aborted" et ferait échouer le
            # fallback (with_mode=False) qui réutilise la même connexion juste après.
            client.rollback()
            return []

        return [
            {
                "text": r["text"],
                "section": r["section"] or "",
                "disease_id": r["disease_id"] or "",
                "cnn_label": r["cnn_label"] or "",
                "nom_fr": r["nom_fr"] or "",
                "mode_conduite": r["mode_conduite"],
                "distance": r["distance"],
            }
            for r in rows
            if r["text"]
        ]

    chunks = run_query(with_mode=True)
    if not chunks:
        chunks = run_query(with_mode=False)

    return chunks
