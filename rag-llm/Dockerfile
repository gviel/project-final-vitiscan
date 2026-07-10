FROM python:3.11-slim

WORKDIR /app

# Limite les pools de threads BLAS/OpenMP/tokenizers : par défaut, torch/numpy dimensionnent ces
# pools sur le nombre de CPU visibles, largement disproportionné par rapport au quota CPU réel
# d'une instance Render gratuite - chaque thread alloue ses propres buffers, ce qui a contribué à
# un OOM en prod (conteneur tué en pleine requête /solutions, cf. docs/refactoring.md).
ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    TOKENIZERS_PARALLELISM=false

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
