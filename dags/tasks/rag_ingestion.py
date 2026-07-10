"""
Tâches du DAG d'ingestion RAG (specs.md, Partie 1) :
détecte les nouveaux documents S3 par rapport à la dernière exécution, ingère dans la branche Neon
de test, puis si OK, ingère dans la branche Neon de prod.

rag-llm/ est monté en lecture seule dans le conteneur Airflow (cf. airflow/docker-compose.yml) et
ses dépendances sont installées dans l'image Airflow (cf. airflow/Dockerfile) : les tâches
importent directement app.ingestion.run_ingestion() en process, pas de subprocess nécessaire (pas
de conflit de dépendances à isoler ici, contrairement à l'entraînement du modèle CNN).
"""
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

from config import (
    AWS_DEFAULT_REGION, DATABASE_URL_PROD, DATABASE_URL_TEST, LAST_INGESTED_VAR, RAG_LLM_DIR,
    RAG_S3_BUCKET, RAG_S3_PREFIX, WORK_DIR,
)

sys.path.insert(0, str(RAG_LLM_DIR))

# Répertoire fixe sous WORK_DIR (bind-mount work/, cf. dags/config.py) plutôt qu'un
# tempfile.mkdtemp() : vidé et réécrit à chaque run (cf. download_and_ingest_test), donc pas
# d'accumulation de dossiers temporaires ni de purge manuelle à faire après coup.
RAG_KNOWLEDGE_WORK_DIR = WORK_DIR / "rag-knowledge"


def _s3_client():
    return boto3.client("s3", region_name=AWS_DEFAULT_REGION)


def _list_knowledge_docs() -> list[dict]:
    """Liste les .md sous s3://RAG_S3_BUCKET/RAG_S3_PREFIX."""
    client = _s3_client()
    paginator = client.get_paginator("list_objects_v2")
    docs = []
    for page in paginator.paginate(Bucket=RAG_S3_BUCKET, Prefix=RAG_S3_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".md"):
                docs.append(obj)
    return docs


def branch_check_new_docs(**context) -> str:
    """
    Compare le document le plus récent de S3 à la Variable LAST_INGESTED_VAR.
    Retourne le prochain task_id ("download_and_ingest_test" ou "stop_dag").
    """
    from airflow.models import Variable

    try:
        docs = _list_knowledge_docs()
    except Exception as exc:
        print(f"[rag_ingestion] WARN listing S3 s3://{RAG_S3_BUCKET}/{RAG_S3_PREFIX} : {exc}")
        return "stop_dag"

    if not docs:
        print(f"[rag_ingestion] Aucun document trouvé sous s3://{RAG_S3_BUCKET}/{RAG_S3_PREFIX}")
        return "stop_dag"

    last_modified = max(doc["LastModified"] for doc in docs)
    last_ingested_str = Variable.get(LAST_INGESTED_VAR, default_var=None)

    if last_ingested_str:
        last_ingested = datetime.fromisoformat(last_ingested_str)
        if last_modified <= last_ingested:
            print(f"[rag_ingestion] Rien de neuf (dernier doc={last_modified.isoformat()} <= dernière ingestion={last_ingested_str})")
            return "stop_dag"

    print(f"[rag_ingestion] {len(docs)} document(s) détecté(s), dernier modifié le {last_modified.isoformat()} - ingestion déclenchée.")
    context["ti"].xcom_push(key="last_modified", value=last_modified.isoformat())
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


def run_golden_prompts_gate(**context) -> None:
    """
    Porte de qualité entre l'ingestion test et la promotion en prod (specs.md : "fait des tests
    pour vérifier que le RAG-LLM répond correctement... si les tests sont OK injecter dans la
    vector db de prod" — jusqu'ici seul le succès technique de l'ingestion faisait foi, cf.
    docs/refactoring.md section 8).

    Rejoue rag-llm/tests/golden_prompts.yaml directement en process contre la branche Neon de test
    qui vient d'être peuplée par download_and_ingest_test (même approche que _run_ingestion : pas
    besoin d'un serveur HTTP rag-llm démarré dans le conteneur Airflow, on importe et on appelle
    directement generate_treatment_advice()).

    Toute panne réelle (cf. app.golden_prompts.GoldenPromptFailure) fait échouer cette tâche, ce
    qui bloque ingest_prod (dépendance de tâche) — les documents ne sont ingérés en prod que si
    tous les cas passent (ou sont explicitement skip, cf. GoldenPromptSkipped : uniquement quand
    le LLM externe est indisponible, hors de portée de cette porte qui vérifie la résolution du
    nommage/dosage, pas la disponibilité du LLM).
    """
    os.environ["DATABASE_URL"] = DATABASE_URL_TEST

    from app.golden_prompts import GoldenPromptFailure, GoldenPromptSkipped, build_payload, evaluate_case, load_cases
    from app.rag_pipeline import generate_treatment_advice

    cases = load_cases()
    n_ok, skipped, failures = 0, [], []

    for case in cases:
        try:
            data = generate_treatment_advice(build_payload(case))
            evaluate_case(data, case)
            n_ok += 1
        except GoldenPromptSkipped as exc:
            skipped.append(f"{case['name']}: {exc}")
        except GoldenPromptFailure as exc:
            failures.append(f"{case['name']}: {exc}")
        except Exception as exc:  # erreur inattendue (ex: base injoignable) - traitée comme un échec
            failures.append(f"{case['name']}: erreur inattendue: {exc}")

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
    """Réingère les mêmes documents dans la branche Neon de prod (n'est atteint que si le test ET les golden prompts ont réussi)."""
    from airflow.models import Variable

    tmp_dir = context["ti"].xcom_pull(task_ids="download_and_ingest_test", key="knowledge_dir")
    _run_ingestion(tmp_dir, DATABASE_URL_PROD)

    last_modified = context["ti"].xcom_pull(task_ids="branch_check_new_docs", key="last_modified")
    Variable.set(LAST_INGESTED_VAR, last_modified or datetime.now(timezone.utc).isoformat())
    print(f"[rag_ingestion] Ingestion prod terminée, {LAST_INGESTED_VAR}={last_modified}")


def _run_ingestion(knowledge_dir: str, database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url

    from app.ingestion import run_ingestion

    n_chunks = run_ingestion(knowledge_dir=Path(knowledge_dir))
    print(f"[rag_ingestion] {n_chunks} chunk(s) ingéré(s) dans la branche Neon ciblée.")
