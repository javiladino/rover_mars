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
    access_key: str | None,
    secret_key: str | None,
    secure: bool = False,
    region: str | None = None,
):
    """
    Construye un cliente MinIO/S3 a partir de parámetros explícitos.

    - secure=False (MinIO local, docker-compose.yml): la región se ignora (MinIO
      standalone no la usa) para no romper el cliente con una región inventada.
    - secure=True (S3 real en AWS): se exige región, requerida por el SDK de S3.
    - secure=True sin access_key/secret_key: usa minio.credentials.IamAwsProvider,
      que lee credenciales temporales del rol IAM del EC2 (mismo mecanismo que usa
      boto3 internamente) — ver specs/002-aws-deployment/research.md, Decisión 1.
      No agrega boto3 como dependencia nueva ni toca ningún call-site de
      .put_object/.fput_object/.get_object en el resto del proyecto: el objeto
      devuelto sigue siendo el mismo cliente Minio de siempre.
    """
    from minio import Minio

    if secure and not access_key and not secret_key:
        from minio.credentials import IamAwsProvider

        return Minio(
            strip_endpoint_scheme(endpoint),
            secure=secure,
            region=region,
            credentials=IamAwsProvider(),
        )

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

    En AWS, MINIO_ACCESS_KEY/MINIO_SECRET_KEY se dejan vacías a propósito (ver
    docker-compose.aws.yml) para que build_object_store_client use el rol IAM
    del EC2. En local, si no están seteadas, se usan las credenciales por
    defecto de MinIO (solo tienen sentido con secure=False).
    """
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
    access_key = os.getenv("MINIO_ACCESS_KEY") or (None if secure else "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY") or (None if secure else "minioadmin")

    return build_object_store_client(
        endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=os.getenv("AWS_REGION", "us-east-1"),
    )
