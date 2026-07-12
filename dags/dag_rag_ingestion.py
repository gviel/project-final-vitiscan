"""
DAG Airflow — Ingestion des documents de connaissance RAG (specs.md, Partie 1).

Détecte les documents markdown nouveaux/modifiés/supprimés dans S3 (comparaison par hash à ce qui
est déjà enregistré dans la branche Neon de prod, cf. tasks/rag_ingestion.py::branch_check_new_docs),
les ingère dans la branche Neon (Postgres/pgvector) de validation, rejoue les golden prompts (porte
de qualité, en HTTP réel contre le service Render vitiscan-rag-llm-validation) contre cette branche
de validation, et seulement si tout est OK, ingère les documents dans la branche Neon de prod
utilisée par rag-llm/.

Chaîne :
  branch_check_new_docs (BranchPythonOperator) :
    - rien de neuf / erreur listing S3 → stop_dag
    - nouveaux docs                    → download_and_ingest_validation >> golden_prompts_gate >> ingest_prod
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator

from config import DAG_RAG_INGESTION_CRON
from tasks.rag_ingestion import (
    branch_check_new_docs, download_and_ingest_validation, ingest_prod, run_golden_prompts_gate,
)

default_args = {
    "owner": "vitiscan",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="dag_rag_ingestion",
    description="Ingère les nouveaux documents de connaissance RAG (S3 -> Neon validation -> golden prompts -> Neon prod)",
    schedule=DAG_RAG_INGESTION_CRON,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["vitiscan", "rag", "ingestion"],
) as dag:

    t_branch = BranchPythonOperator(task_id="branch_check_new_docs", python_callable=branch_check_new_docs)
    t_ingest_validation = PythonOperator(task_id="download_and_ingest_validation", python_callable=download_and_ingest_validation)
    t_golden_prompts_gate = PythonOperator(task_id="golden_prompts_gate", python_callable=run_golden_prompts_gate)
    t_ingest_prod = PythonOperator(task_id="ingest_prod", python_callable=ingest_prod)
    t_stop = EmptyOperator(task_id="stop_dag")

    t_branch >> t_ingest_validation >> t_golden_prompts_gate >> t_ingest_prod
    t_branch >> t_stop
