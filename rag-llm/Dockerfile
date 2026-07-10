FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY db ./db

EXPOSE 9000
# Lit $PORT si fourni par la plateforme d'hébergement (ex: Render), sinon 9000 par défaut (local,
# docker-compose) — forme shell (pas exec) pour que ${PORT:-9000} soit interprété par /bin/sh -c.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-9000}
