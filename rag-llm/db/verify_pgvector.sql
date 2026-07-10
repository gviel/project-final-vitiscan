-- Script de smoke-test pgvector, indépendant du schéma applicatif (rag-llm/db/schema.sql).
-- Sert à vérifier rapidement qu'une instance Postgres (locale ou Neon) supporte bien
-- l'extension vector, la construction d'un index HNSW en distance cosine, et l'opérateur <=>,
-- avant de lancer une vraie ingestion. Usage : psql "$DATABASE_URL" -f rag-llm/db/verify_pgvector.sql

SELECT version();

CREATE EXTENSION IF NOT EXISTS vector;

SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

DROP TABLE IF EXISTS pgvector_probe;

CREATE TABLE pgvector_probe (
    id BIGSERIAL PRIMARY KEY,
    label TEXT,
    embedding VECTOR(384)
);

-- 3 INSERT séparés (et non un seul INSERT...SELECT avec un sous-select non corrélé) :
-- Postgres peut hisser un sous-select non corrélé contenant random() en InitPlan évalué une
-- seule fois et réutilisé pour toutes les lignes, ce qui donnerait 3 vecteurs identiques.
INSERT INTO pgvector_probe (label, embedding)
VALUES ('a', ('[' || array_to_string(array(SELECT round(random()::numeric, 6) FROM generate_series(1, 384)), ',') || ']')::vector);

INSERT INTO pgvector_probe (label, embedding)
VALUES ('b', ('[' || array_to_string(array(SELECT round(random()::numeric, 6) FROM generate_series(1, 384)), ',') || ']')::vector);

INSERT INTO pgvector_probe (label, embedding)
VALUES ('c', ('[' || array_to_string(array(SELECT round(random()::numeric, 6) FROM generate_series(1, 384)), ',') || ']')::vector);

SELECT label, vector_dims(embedding) AS dims FROM pgvector_probe;

CREATE INDEX ON pgvector_probe USING hnsw (embedding vector_cosine_ops);

SELECT b.label, a.embedding <=> b.embedding AS distance
FROM pgvector_probe a, pgvector_probe b
WHERE a.label = 'a'
ORDER BY distance;

EXPLAIN (COSTS OFF)
SELECT label FROM pgvector_probe
ORDER BY embedding <=> (SELECT embedding FROM pgvector_probe WHERE label = 'a')
LIMIT 5;

DROP TABLE pgvector_probe;
