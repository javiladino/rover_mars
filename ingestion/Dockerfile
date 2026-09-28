FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Build context = raíz del repo (ver docker-compose.yml) para poder copiar el
# módulo compartido common/ — ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7.
COPY ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY ingestion/*.py .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/common

CMD ["python", "dsn_receiver.py"]
