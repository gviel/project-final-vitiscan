import os
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

import weaviate
import weaviate.classes as wvc
from weaviate.classes.init import AdditionalConfig, Timeout
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# ---------- Embedder global ----------

_EMBEDDER: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    """Retourne un modèle SentenceTransformer (chargé une seule fois)."""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _EMBEDDER


# ---------- Client Weaviate (context manager) ----------

@contextmanager
def weaviate_client():
    url = (os.getenv("WEAVIATE_URL") or "").strip()
    api_key = (os.getenv("WEAVIATE_API_KEY") or "").strip()

    # Sécurité prod : on refuse localhost si pas de URL cloud
    if not url and (os.getenv("HF_SPACE_ID") or os.getenv("SPACE_ID") or os.getenv("K_SERVICE")):
        raise RuntimeError(
            "WEAVIATE_URL manquant en environnement déployé. "
            "Renseigne WEAVIATE_URL et WEAVIATE_API_KEY."
        )

    if url:
        auth = weaviate.auth.AuthApiKey(api_key) if api_key else None
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=url,
            auth_credentials=auth,
            additional_config=AdditionalConfig(timeout=Timeout(init=30, query=60, insert=60)),
        )
    else:
        client = weaviate.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_PORT", "8080")),
            grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
            additional_config=AdditionalConfig(timeout=Timeout(init=30, query=60, insert=60)),
        )

    try:
        yield client
    finally:
        client.close()


# ---------- Recherche de chunks de traitement ----------

def search_treatment_chunks(
    client: weaviate.WeaviateClient,
    disease_input: str,
    mode: Optional[str],
    severity: Optional[str],
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """
    Retrieval RAG robuste :
    - accepte disease_input au format canonique (ex: "plasmopara_viticola") ou alias court hérité
    - filtre par (cnn_label == ...) OR (disease_id == ...) — les deux propriétés portent
      désormais la même valeur canonique dans le frontmatter des fiches, donc pas besoin de
      deviner laquelle des deux le disease_input représente
    - filtre mode_conduite si fourni, sinon pas de filtre mode
    - fallback : si 0 résultat avec mode -> relance sans mode
    """
    try:
        collection = client.collections.get("VitiScanKnowledge")
    except Exception as e:
        print(f"[RAG] Collection VitiScanKnowledge introuvable: {e}")
        return []

    key = (disease_input or "").strip()
    if not key:
        return []

    cnn_label_value = key
    disease_id_value = key

    query_text = (
        f"Recommandations de traitement vigne pour {key}. "
        f"Mode: {mode or 'non spécifié'}. Gravité: {severity or 'non spécifiée'}. "
        "Inclure diagnostic, actions curatives, prévention, et précautions."
    )

    embedder = get_embedder()
    query_vector = embedder.encode(query_text).tolist()

    filters = []
    if cnn_label_value:
        filters.append(wvc.query.Filter.by_property("cnn_label").equal(cnn_label_value))
    if disease_id_value:
        filters.append(wvc.query.Filter.by_property("disease_id").equal(disease_id_value))

    if not filters:
        return []

    disease_filter = filters[0]
    for f in filters[1:]:
        disease_filter = disease_filter | f

    def run_query(with_mode: bool) -> List[Dict[str, Any]]:
        where_filter = disease_filter
        if with_mode and mode:
            mode_filter = wvc.query.Filter.by_property("mode_conduite").contains_any([mode])
            where_filter = where_filter & mode_filter

        try:
            response = collection.query.near_vector(
                near_vector=query_vector,
                limit=top_k,
                filters=where_filter,
                return_metadata=wvc.query.MetadataQuery(distance=True),
            )
        except Exception as e:
            print(f"[RAG] Erreur near_vector: {e}")
            return []

        chunks: List[Dict[str, Any]] = []
        for obj in response.objects:
            props = obj.properties or {}
            text = props.get("text", "")
            if not text:
                continue

            meta = getattr(obj, "metadata", None)
            distance = getattr(meta, "distance", None) if meta else None

            chunks.append({
                "text": text,
                "section": props.get("section", ""),
                "disease_id": props.get("disease_id", ""),
                "cnn_label": props.get("cnn_label", ""),
                "nom_fr": props.get("nom_fr", ""),
                "mode_conduite": props.get("mode_conduite", None),
                "distance": distance,
            })

        return chunks

    chunks = run_query(with_mode=True)
    if not chunks:
        chunks = run_query(with_mode=False)

    return chunks
