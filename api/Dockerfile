FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY api/app.py api/schemas.py ./

EXPOSE 4000
# Lit $PORT si fourni par la plateforme d'hébergement (ex: Render), sinon 4000 par défaut (local,
# docker-compose) — forme shell (pas exec) pour que ${PORT:-4000} soit interprété par /bin/sh -c.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-4000}
