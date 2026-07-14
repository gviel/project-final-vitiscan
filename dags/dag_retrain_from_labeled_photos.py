"""
DAG Airflow — Ré-entraînement CNN à partir des photos labellisées (specs.md, "Faire évoluer pour
l'AIA" : "détecter si nouvelles images labellisées -> les ajouter dans le dataset et déclencher un
nouvel entraînement").

- détecte les photos acceptées via labeling/ (table Neon vitiscan_photos, cf.
  tasks/photo_retraining.py::branch_check_new_labels) pas encore intégrées au dataset CNN,
- les copie dans organized_data_inrae/train/<human_label>/ (val/test restent fixes),
- déclenche dag_train_model (TriggerDagRunOperator) pour un sweep complet sur le dataset enrichi.

Précondition : le dataset de base (organized_data_inrae/{train,val,test}) doit déjà avoir été
construit par un premier run manuel de dag_train_model - sinon branch_check_new_labels route
directement vers stop_dag (cf. tasks/photo_retraining.py).

Chaîne :
  branch_check_new_labels (BranchPythonOperator) :
    - dataset de base absent / aucune nouvelle photo → stop_dag
    - nouvelles photos acceptées                     → add_to_dataset >> trigger_retrain
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator

from config import DAG_RETRAIN_CRON
from tasks.photo_retraining import add_to_dataset, branch_check_new_labels

default_args = {
    "owner": "vitiscan",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="dag_retrain_from_labeled_photos",
    description="Intègre les photos labellisées (labeling/) au dataset CNN et déclenche dag_train_model",
    schedule=DAG_RETRAIN_CRON,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["vitiscan", "training", "labeling"],
) as dag:

    t_branch = BranchPythonOperator(task_id="branch_check_new_labels", python_callable=branch_check_new_labels)
    t_add_to_dataset = PythonOperator(task_id="add_to_dataset", python_callable=add_to_dataset)
    t_trigger_retrain = TriggerDagRunOperator(task_id="trigger_retrain", trigger_dag_id="dag_train_model")
    t_stop = EmptyOperator(task_id="stop_dag")

    t_branch >> t_add_to_dataset >> t_trigger_retrain
    t_branch >> t_stop
