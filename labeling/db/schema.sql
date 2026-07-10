-- Schéma Postgres du photo labeling dashboard (photos envoyées par les viticulteurs via ui/,
-- labellisées manuellement via labeling/ pour calculer le drift avec la prod). Exécuté de façon
-- idempotente par ensure_schema() (ui/storage.py ET labeling/db.py, cf. commentaire dans ces deux
-- fichiers), pas de système de migration versionné à ce stade du projet (même convention que
-- rag-llm/db/schema.sql). Domaine séparé de rag-llm/db/schema.sql (RAG) : pas de FK/dépendance
-- entre les deux, tables non liées.

CREATE TABLE IF NOT EXISTS vitiscan_photos (
    id               BIGSERIAL PRIMARY KEY,

    -- Stockage S3 ---------------------------------------------------------------
    s3_bucket        TEXT NOT NULL,
    s3_key           TEXT NOT NULL UNIQUE,       -- ex: user-photos/2026/07/10/<hash>_<uuid>.jpg
    -- sha256 du contenu brut, calculé avant upload par ui/storage.py (dédup) - pas l'ETag S3
    -- (contrairement à rag_knowledge_manifest) car le fichier est déjà en mémoire côté UI, pas
    -- besoin d'un aller-retour S3 pour l'obtenir. Pas de contrainte UNIQUE : deux photos
    -- identiques légitimes (même feuille photographiée deux fois) doivent pouvoir coexister - la
    -- dédup est un filtre visuel dans labeling/, pas un blocage à l'insertion.
    content_hash     TEXT NOT NULL,

    -- Métadonnées de soumission ---------------------------------------------------
    submitted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL si pas de tag EXIF DateTimeOriginal (cf. ui/app.py::get_exif_data)
    exif_captured_at TIMESTAMPTZ,
    -- NULL si pas de tag EXIF GPSInfo - jamais 0.0 factice (get_exif_data renvoie (0.0, 0.0) en
    -- fallback UI pour centrer la carte Folium, converti en NULL avant insert par ui/storage.py).
    gps_lat          DOUBLE PRECISION,
    gps_lon          DOUBLE PRECISION,

    -- Prédiction CNN au moment de la soumission ------------------------------------
    predicted_label  TEXT NOT NULL,              -- predictions[0].disease (meilleure prédiction)
    confidence       DOUBLE PRECISION NOT NULL,  -- predictions[0].confidence
    raw_predictions  JSONB NOT NULL,              -- diagnostic['predictions'] complet (toutes classes)
    model_version    TEXT NOT NULL,               -- diagnostic['model_version'], nom lisible (pas un run_id MLflow)

    -- Labellisation humaine (labeling/), NULL = non labellisé ----------------------
    human_label      TEXT,
    labeled_at       TIMESTAMPTZ,
    labeled_by       TEXT                         -- champ libre saisi dans labeling/, pas d'auth dans ce projet
);

CREATE INDEX IF NOT EXISTS vitiscan_photos_content_hash_idx    ON vitiscan_photos (content_hash);
CREATE INDEX IF NOT EXISTS vitiscan_photos_model_version_idx   ON vitiscan_photos (model_version);
CREATE INDEX IF NOT EXISTS vitiscan_photos_predicted_label_idx ON vitiscan_photos (predicted_label);
CREATE INDEX IF NOT EXISTS vitiscan_photos_submitted_at_idx    ON vitiscan_photos (submitted_at DESC);
-- Filtre "non labellisé" fréquent dans le dashboard : index partiel, léger et ciblé.
CREATE INDEX IF NOT EXISTS vitiscan_photos_unlabeled_idx ON vitiscan_photos (submitted_at) WHERE human_label IS NULL;
