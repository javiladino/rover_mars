FROM apache/airflow:2.9.1-python3.11

# Build context = raíz del repo (ver docker-compose.yml) para poder copiar el
# módulo compartido common/ — ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7.
COPY airflow/requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

COPY common/ /opt/airflow/common/
