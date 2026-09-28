"""
Tests del módulo compartido de almacenamiento (common/rovermars_common/storage.py).

Ver Fase 7 de docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md: antes de este módulo,
simulator/, ingestion/ y airflow/ construían cada uno su propio cliente MinIO/S3,
con lógica ligeramente distinta entre sí. Estos tests fijan el comportamiento
esperado de la fábrica única para que no vuelva a divergir.
"""

from rovermars_common.storage import build_object_store_client, strip_endpoint_scheme


def test_strip_endpoint_scheme_removes_http():
    assert strip_endpoint_scheme("http://minio:9000") == "minio:9000"


def test_strip_endpoint_scheme_removes_https():
    assert strip_endpoint_scheme("https://s3.amazonaws.com") == "s3.amazonaws.com"


def test_strip_endpoint_scheme_is_idempotent():
    once = strip_endpoint_scheme("http://minio:9000")
    twice = strip_endpoint_scheme(once)
    assert once == twice == "minio:9000"


def test_strip_endpoint_scheme_leaves_bare_host_unchanged():
    # Caso AWS real: MINIO_ENDPOINT="s3.amazonaws.com", sin esquema.
    assert strip_endpoint_scheme("s3.amazonaws.com") == "s3.amazonaws.com"


def test_build_object_store_client_local_minio_ignores_region():
    client = build_object_store_client(
        endpoint="http://minio:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False,
        region="us-east-1",
    )
    assert client is not None


def test_build_object_store_client_aws_s3_secure():
    client = build_object_store_client(
        endpoint="s3.amazonaws.com",
        access_key="AKIA_EXAMPLE",
        secret_key="secret",
        secure=True,
        region="us-east-1",
    )
    assert client is not None
