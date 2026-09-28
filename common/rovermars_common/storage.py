"""
Fábrica única de clientes de almacenamiento de objetos (MinIO local / S3 real en AWS).

Antes de este módulo, `simulator/mastcamz_simulator.py`, `ingestion/dsn_receiver.py`
y `airflow/dags/mastcamz_pipeline.py` construían cada uno su propio cliente Minio,
con lógica de "secure"/"region" ligeramente distinta entre sí -- una de las tres
copias ni siquiera usaba las credenciales recibidas (bug corregido por separado).
Esta duplicación viola separación de responsabilidades: tres servicios reimplementando
la misma decisión de infraestructura, con riesgo real de que diverjan (ya había pasado).

Responsabilidad única de este módulo: construir un cliente S3-compatible correctamente
configurado a partir de parámetros explícitos. No sabe nada de Kafka, Postgres, ni de
la lógica de negocio de ningún servicio — por eso es trivial de testear (ver
tests/test_storage.py) sin necesitar un MinIO/S3 real levantado.
"""

from __future__ import annotations

import os


def strip_endpoint_scheme(endpoint: str) -> str:
    """Quita el prefijo http:// o https:// de un endpoint, si lo tiene.

    Es idempotente: aplicarla dos veces da el mismo resultado que aplicarla una vez,
    y un endpoint que ya viene sin esquema (p.ej. "s3.amazonaws.com" en AWS) queda
    igual.
    """
    return endpoint.replace("http://", "").replace("https://", "")


def build_object_store_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
    region: str | None = None,
):
    """
    Construye un cliente MinIO/S3 a partir de parámetros explícitos.

    - secure=False (MinIO local, docker-compose.yml): la región se ignora (MinIO
      standalone no la usa) para no romper el cliente con una región inventada.
    - secure=True (S3 real en AWS): se exige región, requerida por el SDK de S3.
    """
    from minio import Minio

    return Minio(
        strip_endpoint_scheme(endpoint),
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region if secure else None,
    )


def object_store_client_from_env():
    """
    Construye el cliente leyendo las variables de entorno estándar del proyecto —
    las mismas en los tres servicios (ver .env.example):
    MINIO_ENDPOINT, MINIO_SECURE, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, AWS_REGION.
    """
    return build_object_store_client(
        endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        region=os.getenv("AWS_REGION", "us-east-1"),
    )
