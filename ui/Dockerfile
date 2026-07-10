FROM python:3.11-slim

WORKDIR /app

COPY ui/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY ui/app.py .
COPY ui/storage.py .
COPY ui/.streamlit ./.streamlit

# Source unique labeling/db/schema.sql (cf. ui/storage.py::_SCHEMA_SQL_CANDIDATES) : copié ici au
# lieu d'être dupliqué à la main, pour rester automatiquement synchronisé avec labeling/.
COPY labeling/db/schema.sql ./db/schema.sql

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
