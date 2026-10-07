"""
Tests del módulo compartido de almacenamiento (common/rovermars_common/storage.py).

Ver Fase 7 de docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md: antes de este módulo,
simulator/, ingestion/ y airflow/ construían cada uno su propio cliente MinIO/S3,
con lógica ligeramente distinta entre sí. Estos tests fijan el comportamiento
esperado de la fábrica única para que no vuelva a divergir.
"""

from unittest.mock import patch

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


def test_build_object_store_client_uses_iam_role_when_secure_without_keys():
    # Caso real del EC2 (ver specs/002-aws-deployment/research.md, Decisión 1):
    # AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY quedan vacías a propósito para
    # usar el rol IAM de la instancia en vez de claves estáticas.
    with (
        patch("minio.credentials.IamAwsProvider") as iam_provider,
        patch("minio.Minio") as minio_cls,
    ):
        build_object_store_client(
            endpoint="s3.amazonaws.com",
            access_key=None,
            secret_key=None,
            secure=True,
            region="us-east-1",
        )

        iam_provider.assert_called_once_with()
        _, kwargs = minio_cls.call_args
        assert kwargs["credentials"] is iam_provider.return_value
        assert "access_key" not in kwargs
        assert "secret_key" not in kwargs


def test_build_object_store_client_local_minio_without_keys_stays_static():
    # secure=False (MinIO local) nunca debe tomar el camino de IamAwsProvider,
    # aunque no se pasen claves -- ese caso no debería darse (object_store_client_from_env
    # siempre default-ea a "minioadmin" cuando secure=False), pero si pasara,
    # el comportamiento correcto es construir el cliente igual, sin credenciales
    # de rol IAM que no tienen sentido fuera de AWS.
    with (
        patch("minio.credentials.IamAwsProvider") as iam_provider,
        patch("minio.Minio"),
    ):
        build_object_store_client(
            endpoint="http://minio:9000",
            access_key=None,
            secret_key=None,
            secure=False,
            region=None,
        )

        iam_provider.assert_not_called()
