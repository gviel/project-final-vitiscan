# Image Airflow avec les dépendances des DAGs "métier" :
# - ingestion RAG (app.ingestion tourne en process dans ce conteneur, cf.
#   dags/tasks/rag_ingestion.py) ;
# - sweep multi-modèles CNN (train.py tourne en subprocess dans ce même conteneur, cf.
#   dags/tasks/train_model.py) - même choix que le DAG training du projet Fraud Detection : pas
#   de conteneur Docker séparé pour l'entraînement (jugé trop complexe pour ce projet), les deps
#   ML lourdes sont installées directement dans l'image Airflow.
FROM apache/airflow:3.2.2-python3.12

USER airflow

COPY rag-llm/requirements.txt /tmp/requirements-rag-llm.txt
RUN pip install --no-cache-dir -r /tmp/requirements-rag-llm.txt

COPY training/requirements.txt /tmp/requirements-training.txt
RUN pip install --no-cache-dir -r /tmp/requirements-training.txt
