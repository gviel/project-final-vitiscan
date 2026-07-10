"""
Tâches du DAG d'ingestion RAG (specs.md, Partie 1) :
détecte les documents S3 nouveaux/modifiés/supprimés par rapport au manifest déjà enregistré dans
la branche Neon de PROD (table rag_knowledge_manifest, cf. rag-llm/db/schema.sql), ingère dans la
branche Neon de test, puis si OK (golden prompts), ingère dans la branche Neon de prod et met à
jour son manifest.

Avant ce fichier comparait juste le LastModified S3 le plus récent à une Variable Airflow
(timestamp de la dernière ingestion réussie) : ça ratait les modifications de contenu à date
inchangée et les suppressions, et surtout ignorait totalement que DATABASE_URL_TEST/PROD peuvent
avoir changé de branche Neon entre deux runs (la Variable disait "déjà ingéré" alors que la branche
réellement ciblée aujourd'hui pouvait être vide - constaté en test réel). Comparer directement au
contenu de la base cible élimine cette classe de bug par construction.

rag-llm/ est monté en lecture seule dans le conteneur Airflow (cf. airflow/docker-compose.yml) et
ses dépendances sont installées dans l'image Airflow (cf. airflow/Dockerfile) : les tâches
importent directement app.ingestion.run_ingestion() en process, pas de subprocess nécessaire (pas
de conflit de dépendances à isoler ici, contrairement à l'entraînement du modèle CNN).
"""
import os
import shutil
import sys
import time
from pathlib import Path

import boto3
import psycopg
import requests

from config import (
    AWS_DEFAULT_REGION, DATABASE_URL_PROD, DATABASE_URL_TEST, RAG_LLM_DIR,
    RAG_LLM_TEST_URL, RAG_S3_BUCKET, RAG_S3_PREFIX, WORK_DIR,
)

sys.path.insert(0, str(RAG_LLM_DIR))

# Répertoire fixe sous WORK_DIR (bind-mount work/, cf. dags/config.py) plutôt qu'un
# tempfile.mkdtemp() : vidé et réécrit à chaque run (cf. download_and_ingest_test), donc pas
# d'accumulation de dossiers temporaires ni de purge manuelle à faire après coup.
RAG_KNOWLEDGE_WORK_DIR = WORK_DIR / "rag-knowledge"

# Réutilise le même schema.sql que rag-llm/app/ingestion.py::ensure_schema (table
# rag_knowledge_manifest incluse, cf. rag-llm/db/schema.sql) - une seule source de vérité pour le
# DDL, appliqué de façon idempotente avant chaque lecture/écriture du manifest.
MANIFEST_SCHEMA_SQL_PATH = RAG_LLM_DIR / "db" / "schema.sql"


def _s3_client():
    return boto3.client("s3", region_name=AWS_DEFAULT_REGION)


def _list_knowledge_docs() -> list[dict]:
    """Liste les .md sous s3://RAG_S3_BUCKET/RAG_S3_PREFIX (avec leur ETag, cf. _s3_manifest)."""
    client = _s3_client()
    paginator = client.get_paginator("list_objects_v2")
    docs = []
    for page in paginator.paginate(Bucket=RAG_S3_BUCKET, Prefix=RAG_S3_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".md"):
                docs.append(obj)
    return docs


def _s3_manifest(docs: list) -> dict:
    """
    {nom_de_fichier: hash} à partir de l'ETag S3 (MD5 du contenu pour un upload simple/non
    multipart - toujours le cas ici vu la taille des fiches .md) : évite de télécharger chaque
    fichier juste pour le hasher, list_objects_v2 le fournit déjà gratuitement.
    """
    return {Path(doc["Key"]).name: doc["ETag"].strip('"') for doc in docs}


def _ensure_manifest_table(conn) -> None:
    conn.execute(MANIFEST_SCHEMA_SQL_PATH.read_text())
    conn.commit()


def _fetch_manifest(database_url: str) -> dict:
    """Manifest {filename: hash} actuellement enregistré dans la branche Neon donnée."""
    with psycopg.connect(database_url) as conn:
        _ensure_manifest_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT filename, content_hash FROM rag_knowledge_manifest")
            return dict(cur.fetchall())


def _write_manifest(database_url: str, manifest: dict) -> None:
    """Remplace le contenu de rag_knowledge_manifest par `manifest` (même logique de ré-écriture
    complète que le TRUNCATE + réinsertion des chunks, cf. app.ingestion.ingest_chunks_into_db)."""
    with psycopg.connect(database_url) as conn:
        _ensure_manifest_table(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE rag_knowledge_manifest;")
            for filename, content_hash in manifest.items():
                cur.execute(
                    "INSERT INTO rag_knowledge_manifest (filename, content_hash) VALUES (%s, %s)",
                    (filename, content_hash),
                )
        conn.commit()


def branch_check_new_docs(**context) -> str:
    """
    Compare le manifest S3 courant (nom de fichier + hash) au manifest déjà enregistré dans la
    branche Neon de PROD. Retourne le prochain task_id ("download_and_ingest_test" ou "stop_dag").
    """
    try:
        docs = _list_knowledge_docs()
    except Exception as exc:
        print(f"[rag_ingestion] WARN listing S3 s3://{RAG_S3_BUCKET}/{RAG_S3_PREFIX} : {exc}")
        return "stop_dag"

    if not docs:
        print(f"[rag_ingestion] Aucun document trouvé sous s3://{RAG_S3_BUCKET}/{RAG_S3_PREFIX}")
        return "stop_dag"

    s3_manifest = _s3_manifest(docs)
    try:
        prod_manifest = _fetch_manifest(DATABASE_URL_PROD)
    except Exception as exc:
        print(f"[rag_ingestion] WARN lecture manifest prod : {exc} - ingestion déclenchée par prudence.")
        prod_manifest = {}

    if s3_manifest == prod_manifest:
        print("[rag_ingestion] Rien de neuf (S3 identique au manifest déjà en prod).")
        return "stop_dag"

    added = sorted(set(s3_manifest) - set(prod_manifest))
    removed = sorted(set(prod_manifest) - set(s3_manifest))
    modified = sorted(f for f in (set(s3_manifest) & set(prod_manifest)) if s3_manifest[f] != prod_manifest[f])
    print(f"[rag_ingestion] Changements détectés - ajoutés={added}, modifiés={modified}, supprimés={removed} - ingestion déclenchée.")
    context["ti"].xcom_push(key="s3_manifest", value=s3_manifest)
    return "download_and_ingest_test"


def download_and_ingest_test(**context) -> str:
    """
    Télécharge les docs S3 dans RAG_KNOWLEDGE_WORK_DIR (work/rag-knowledge/, cf. module) et les
    ingère dans la branche Neon de test. Le répertoire est vidé avant chaque téléchargement (pas
    seulement écrasé) pour éviter qu'un fichier supprimé côté S3 reste ingéré par erreur depuis un
    run précédent.
    """
    client = _s3_client()
    docs = _list_knowledge_docs()

    work_dir = RAG_KNOWLEDGE_WORK_DIR
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    for doc in docs:
        dest = work_dir / Path(doc["Key"]).name
        client.download_file(RAG_S3_BUCKET, doc["Key"], str(dest))
    print(f"[rag_ingestion] {len(docs)} document(s) téléchargé(s) dans {work_dir}")

    _run_ingestion(str(work_dir), DATABASE_URL_TEST)

    context["ti"].xcom_push(key="knowledge_dir", value=str(work_dir))
    return str(work_dir)


def _wait_for_rag_llm_test_ready(url: str, timeout: int = 180, interval: int = 5) -> None:
    """
    Poll GET {url}/health jusqu'à succès ou timeout. Le service Render vitiscan-rag-llm-test est
    sur le plan free : après 15 min sans requête, il se met en veille et met jusqu'à ~30-90s à se
    réveiller (cf. docs/deploiement-render-streamlit.md) - sans cette attente, le premier appel
    /solutions échouerait pour une raison purement infra, pas un vrai échec de golden prompt.
    """
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{url}/health", timeout=10)
            resp.raise_for_status()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(interval)
    raise RuntimeError(f"vitiscan-rag-llm-test ({url}) ne répond pas sur /health après {timeout}s : {last_error}")


def run_golden_prompts_gate(**context) -> None:
    """
    Porte de qualité entre l'ingestion test et la promotion en prod (specs.md : "fait des tests
    pour vérifier que le RAG-LLM répond correctement... si les tests sont OK injecter dans la
    vector db de prod" — jusqu'ici seul le succès technique de l'ingestion faisait foi, cf.
    docs/refactoring.md section 8).

    Rejoue rag-llm/tests/golden_prompts.yaml en HTTP réel contre le service Render
    vitiscan-rag-llm-test (RAG_LLM_TEST_URL, cf. render.yaml et dags/config.py), qui pointe sur la
    branche Neon de test qui vient d'être peuplée par download_and_ingest_test. Contrairement à un
    appel en process de generate_treatment_advice(), ceci teste aussi le service réellement
    déployé (Dockerfile, variables d'env Render, limites du plan free...) - les deux bugs de
    déploiement déjà rencontrés (rootDir cassant dockerfilePath/dockerContext, OOM torch CUDA
    involontaire, cf. docs/refactoring.md) n'auraient pas été détectés par un test en process.

    Toute panne réelle (cf. app.golden_prompts.GoldenPromptFailure) fait échouer cette tâche, ce
    qui bloque ingest_prod (dépendance de tâche) — les documents ne sont ingérés en prod que si
    tous les cas passent (ou sont explicitement skip, cf. GoldenPromptSkipped : uniquement quand
    le LLM externe est indisponible, hors de portée de cette porte qui vérifie la résolution du
    nommage/dosage, pas la disponibilité du LLM).
    """
    if not RAG_LLM_TEST_URL:
        raise RuntimeError("RAG_LLM_TEST_URL manquant, cf. airflow/.env.template")

    from app.golden_prompts import GoldenPromptSkipped, build_payload, evaluate_case, load_cases

    _wait_for_rag_llm_test_ready(RAG_LLM_TEST_URL)

    cases = load_cases()
    n_ok, skipped, failures = 0, [], []

    for case in cases:
        try:
            resp = requests.post(f"{RAG_LLM_TEST_URL}/solutions", json=build_payload(case), timeout=90)
            resp.raise_for_status()
            evaluate_case(resp.json()["data"], case)
            n_ok += 1
        except GoldenPromptSkipped as exc:
            skipped.append(f"{case['name']}: {exc}")
        except Exception as exc:  # GoldenPromptFailure, erreur HTTP, base injoignable... = échec
            failures.append(f"{case['name']}: {exc}")

    print(f"[rag_ingestion] Golden prompts : {n_ok} OK, {len(skipped)} skip, {len(failures)} échec(s) sur {len(cases)} cas.")
    for s in skipped:
        print(f"[rag_ingestion]   SKIP {s}")
    for f in failures:
        print(f"[rag_ingestion]   FAIL {f}")

    if failures:
        raise RuntimeError(
            f"{len(failures)} golden prompt(s) en échec — promotion vers la branche Neon de prod annulée : {failures}"
        )


def ingest_prod(**context):
    """
    Réingère les mêmes documents dans la branche Neon de prod (n'est atteint que si le test ET les
    golden prompts ont réussi), puis met à jour son manifest (rag_knowledge_manifest) avec l'état
    S3 qui vient d'être promu - c'est ce manifest que branch_check_new_docs relira au prochain run
    pour décider s'il y a du nouveau.
    """
    tmp_dir = context["ti"].xcom_pull(task_ids="download_and_ingest_test", key="knowledge_dir")
    _run_ingestion(tmp_dir, DATABASE_URL_PROD)

    s3_manifest = context["ti"].xcom_pull(task_ids="branch_check_new_docs", key="s3_manifest")
    _write_manifest(DATABASE_URL_PROD, s3_manifest)
    print(f"[rag_ingestion] Ingestion prod terminée, manifest mis à jour ({len(s3_manifest)} fichier(s)).")


def _run_ingestion(knowledge_dir: str, database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url

    from app.ingestion import run_ingestion

    n_chunks = run_ingestion(knowledge_dir=Path(knowledge_dir))
    print(f"[rag_ingestion] {n_chunks} chunk(s) ingéré(s) dans la branche Neon ciblée.")
