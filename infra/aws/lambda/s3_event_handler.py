"""
Lambda de ejemplo (ADR-016) — se dispara ante ObjectCreated en el bucket
`raw` del data lake (ADR-012) y hace una validación ligera antes de que
Airflow procese el objeto: existencia, tamaño > 0, extensión esperada.

No reemplaza la validación de validate_raw_products() en el DAG — es un
primer filtro rápido, más cercano al patrón event-driven nativo de AWS.
"""

import json
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

VALID_EXTENSIONS = (".IMG", ".xml", ".json")


def handler(event, context):
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            size = head["ContentLength"]
            valid_ext = key.endswith(VALID_EXTENSIONS)
            valid = size > 0 and valid_ext

            logger.info(
                "Objeto %s/%s size=%s valid_ext=%s valid=%s",
                bucket, key, size, valid_ext, valid,
            )
            results.append({"key": key, "size": size, "valid": valid})

        except Exception as exc:  # noqa: BLE001 — Lambda debe seguir procesando el resto de records
            logger.error("Error validando %s/%s: %s", bucket, key, exc)
            results.append({"key": key, "error": str(exc)})

    return {"statusCode": 200, "body": json.dumps(results)}
