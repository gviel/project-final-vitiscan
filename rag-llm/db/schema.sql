-- Schéma pgvector de la base de connaissances RAG (remplace la collection Weaviate
-- "VitiScanKnowledge"). Exécuté de façon idempotente par app.vector_store.ensure_schema()
-- à chaque démarrage/ingestion, pas de système de migration versionné à ce stade du projet.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS vitiscan_knowledge (
    id            BIGSERIAL PRIMARY KEY,
    text          TEXT NOT NULL,
    section       TEXT,
    disease_id    TEXT,
    cnn_label     TEXT,
    nom_fr        TEXT,
    type          TEXT,
    categorie     TEXT,
    mode_conduite TEXT[],
    -- 384 = dimension de sentence-transformers/all-MiniLM-L6-v2 (inchangée depuis Weaviate)
    embedding     VECTOR(384) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW + cosine : équivalent du comportement par défaut de Weaviate (vectors self_provided,
-- distance cosine), et ne nécessite pas de données préexistantes pour être construit
-- (contrairement à IVFFlat).
CREATE INDEX IF NOT EXISTS vitiscan_knowledge_embedding_hnsw_idx
    ON vitiscan_knowledge USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS vitiscan_knowledge_disease_id_idx ON vitiscan_knowledge (disease_id);
CREATE INDEX IF NOT EXISTS vitiscan_knowledge_cnn_label_idx  ON vitiscan_knowledge (cnn_label);

-- mode_conduite est un TEXT[] (équivalent du contains_any() Weaviate via l'opérateur && ),
-- indexable via GIN.
CREATE INDEX IF NOT EXISTS vitiscan_knowledge_mode_conduite_gin_idx
    ON vitiscan_knowledge USING GIN (mode_conduite);
