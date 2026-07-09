import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import frontmatter
import weaviate
import weaviate.classes as wvc

from app.weaviate_client import weaviate_client, get_embedder

# Nom de la collection dans Weaviate
COLLECTION_NAME = "VitiScanKnowledge"


def load_markdown_files(knowledge_dir: Path) -> List[Dict[str, Any]]:
    """Charge tous les fichiers .md du dossier data/knowledge et retourne une liste de {path, meta, content}."""
    md_files = sorted(knowledge_dir.glob("*.md"))
    fiches: List[Dict[str, Any]] = []

    for md_path in md_files:
        post = frontmatter.load(md_path)
        fiches.append({
            "path": str(md_path),
            "meta": dict(post.metadata),
            "content": post.content,
        })

    return fiches


def split_markdown_sections(content: str) -> List[Dict[str, str]]:
    """
    Découpe le contenu markdown en sections à partir des titres de niveau 1 '# '.
    Retourne une liste de {"section_title": ..., "text": ...}.
    """
    lines = content.splitlines()
    sections: List[Dict[str, str]] = []

    current_title: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        heading_match = re.match(r"^#\s+(.*)", line.strip())
        if heading_match:
            if current_title is not None and current_lines:
                sections.append({"section_title": current_title, "text": "\n".join(current_lines).strip()})
            current_title = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title is not None and current_lines:
        sections.append({"section_title": current_title, "text": "\n".join(current_lines).strip()})

    return sections


def ensure_collection(client: weaviate.WeaviateClient):
    """Crée la collection VitiScanKnowledge si elle n'existe pas déjà (vectors: self_provided)."""
    collections = client.collections
    try:
        coll = collections.get(COLLECTION_NAME)
        _ = coll.config.get()
        return coll
    except Exception:
        return collections.create(
            name=COLLECTION_NAME,
            vector_config=wvc.config.Configure.Vectors.self_provided(),
            properties=[
                wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="section", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="disease_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="cnn_label", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="nom_fr", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="type", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="categorie", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="mode_conduite", data_type=wvc.config.DataType.TEXT),
            ],
        )


def build_chunk_objects(fiches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transforme les fiches markdown en chunks prêts à être indexés :
    - text: titre de section + contenu
    - section, disease_id, cnn_label, nom_fr, type, categorie, mode_conduite: depuis le front matter
    """
    all_chunks: List[Dict[str, Any]] = []

    for fiche in fiches:
        meta = fiche["meta"]
        sections = split_markdown_sections(fiche["content"])
        mode_conduite_str = ", ".join(meta.get("mode_conduite") or [])

        for section in sections:
            all_chunks.append({
                "text": f"{section['section_title']}\n\n{section['text']}".strip(),
                "section": section["section_title"],
                "disease_id": meta.get("id"),
                "cnn_label": meta.get("cnn_label"),
                "nom_fr": meta.get("nom_fr"),
                "type": meta.get("type"),
                "categorie": meta.get("categorie"),
                "mode_conduite": mode_conduite_str,
            })

    return all_chunks


def ingest_chunks_into_weaviate(chunks: List[Dict[str, Any]]) -> None:
    """Envoie tous les chunks dans Weaviate avec des embeddings SentenceTransformer."""
    with weaviate_client() as client:
        collection = ensure_collection(client)

        print(f"[INGESTION] Nombre de chunks à indexer: {len(chunks)}")
        embedder = get_embedder()

        with collection.batch.dynamic() as batch:
            for idx, chunk in enumerate(chunks, start=1):
                vector = embedder.encode(chunk["text"]).tolist()
                batch.add_object(
                    properties={k: chunk[k] for k in (
                        "text", "section", "disease_id", "cnn_label", "nom_fr", "type", "categorie", "mode_conduite"
                    )},
                    vector=vector,
                )
                if idx % 20 == 0:
                    print(f"[INGESTION] {idx} chunks envoyés...")

            if batch.number_errors > 0:
                print(f"[INGESTION] Erreurs lors de l'import: {batch.number_errors}")
                print(batch.failed_objects)

        print("[INGESTION] Import terminé.")


def run_ingestion(knowledge_dir: Optional[Path] = None) -> int:
    """Point d'entrée réutilisable (CLI, script, futur DAG Airflow). Retourne le nombre de chunks indexés."""
    if knowledge_dir is None:
        knowledge_dir = Path(__file__).resolve().parents[1] / "data" / "knowledge"

    print(f"[INGESTION] Lecture des fiches dans {knowledge_dir}")
    fiches = load_markdown_files(knowledge_dir)
    print(f"[INGESTION] Fichiers markdown détectés: {len(fiches)}")

    chunks = build_chunk_objects(fiches)
    print(f"[INGESTION] Chunks générés: {len(chunks)}")
    if chunks:
        print("[INGESTION] Exemple de chunk:")
        print(json.dumps(chunks[0], indent=2, ensure_ascii=False))

    ingest_chunks_into_weaviate(chunks)
    return len(chunks)


if __name__ == "__main__":
    run_ingestion()
