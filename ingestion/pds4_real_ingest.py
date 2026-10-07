"""
Ingesta acotada de productos reales de Mastcam-Z desde el archivo público PDS
de JPL (bundle "ops_raw", sin calibrar -- ver specs/002-aws-deployment/research.md,
Decisión 2) hacia la capa Raw local del proyecto.

No es un servicio continuo ni corre dentro de un DAG: es un script de ingesta
puntual, pensado para un subconjunto chico de sols (Escenario 2 de
specs/002-aws-deployment/spec.md). El simulador sigue siendo la única fuente
del tramo CCSDS/DSN -- este script no lo reemplaza, convive con él.

Formato real de producto (verificado contra el archivo público, no inventado):
    ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.IMG
    ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.xml
Prefijo de cámara (ZL=izquierda, ZR=derecha), sol, SCLK, resto de campos de
la misión real. Distinto del formato M20_MCZL_... que documenta el
simulador, que es una convención simplificada, no la real (ver research.md).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

BUNDLE_ROOT_URL = "https://planetarydata.jpl.nasa.gov/img/data/mars2020/mars2020_mastcamz_ops_raw"
MANIFEST_URL = f"{BUNDLE_ROOT_URL}/data/collection_data_inventory.csv"

POSTGRES_CONN = os.getenv(
    "POSTGRES_CONN", "postgresql://rover:rover2024@localhost:5432/rover_mars"
)
RAW_BUCKET = os.getenv("S3_BUCKET_RAW", "mastcamz-raw")

# Prefijo de cámara real -- ver docstring del módulo.
_CAMERA_PREFIX_TO_EYE = {"ZL": "LEFT", "ZR": "RIGHT"}

_FILENAME_RE = re.compile(r"^(?P<camera>Z[LR])\w?_(?P<sol>\d{4})_(?P<sclk>\d+)_.+$")


@dataclass(frozen=True)
class ProductoPDS4Real:
    """Un producto real identificado en el manifiesto -- ver data-model.md."""

    product_id: str  # nombre de archivo sin extensión
    sol: int
    sclk: float
    camera_eye: str  # "LEFT" | "RIGHT"
    img_url: str
    label_url: str
    checksum_manifiesto: str | None


class ChecksumMismatchError(ValueError):
    """El contenido descargado no coincide con el checksum del manifiesto (FR-004)."""


def parse_product_filename(filename_without_ext: str) -> dict:
    """
    Extrae sol, sclk y cámara del nombre real de un producto PDS4 de Mastcam-Z.

    Lanza ValueError si el nombre no respeta el formato real verificado
    (ver docstring del módulo) -- un producto con nombre inesperado no se
    acepta silenciosamente.
    """
    match = _FILENAME_RE.match(filename_without_ext)
    if not match:
        raise ValueError(
            f"Nombre de producto PDS4 real con formato inesperado: {filename_without_ext!r}"
        )
    return {
        "camera_eye": _CAMERA_PREFIX_TO_EYE[match.group("camera")],
        "sol": int(match.group("sol")),
        "sclk": float(match.group("sclk")),
    }


def _detect_column(fieldnames: list[str], *candidates: str) -> str | None:
    """
    Busca, sin distinguir mayúsculas, una columna del manifiesto cuyo nombre
    contenga alguno de los `candidates`. Devuelve None si ninguna coincide,
    en vez de fallar -- quien llama decide si esa columna es obligatoria.

    El manifiesto real (~44 MB, ver research.md Decisión 2) no se inspeccionó
    celda por celda en esta sesión (no se descargó un archivo de 44 MB solo
    para verificar encabezados). Antes de la primera corrida real (tarea
    T021 de tasks.md), confirmar los nombres reales de columna con:
        curl -s -r 0-2000 <MANIFEST_URL>
    y ajustar las listas de `candidates` en select_bounded_subset() si no
    coinciden -- fetch_manifest()/select_bounded_subset() están separadas de
    la descarga de red precisamente para poder ajustar esto sin tocar el
    resto del script.
    """
    lowered = {name.lower(): name for name in fieldnames}
    for candidate in candidates:
        for lower_name, original_name in lowered.items():
            if candidate in lower_name:
                return original_name
    return None


def select_bounded_subset(
    manifest_rows: list[dict], sols: list[int]
) -> list[ProductoPDS4Real]:
    """
    Filtra el manifiesto ya descargado a un subconjunto acotado de sols
    (FR del Escenario 2 de spec.md). No recorre el árbol del archivo --
    opera sobre las filas que ya trajo fetch_manifest().
    """
    if not manifest_rows:
        return []

    fieldnames = list(manifest_rows[0].keys())
    file_col = _detect_column(fieldnames, "file", "path", "name")
    if file_col is None:
        raise ValueError(
            f"No se encontró columna de nombre de archivo en {fieldnames} -- "
            "ver nota de _detect_column sobre verificar el manifiesto real."
        )
    checksum_col = _detect_column(fieldnames, "md5", "checksum", "hash")
    if checksum_col is None:
        logger.warning("El manifiesto no tiene columna de checksum reconocible")

    productos: list[ProductoPDS4Real] = []
    for row in manifest_rows:
        file_path = row[file_col]
        if not file_path.lower().endswith(".img"):
            continue

        filename = PurePosixPath(file_path).stem
        try:
            parsed = parse_product_filename(filename)
        except ValueError:
            continue
        if parsed["sol"] not in sols:
            continue

        label_path = str(PurePosixPath(file_path).with_suffix(".xml"))
        productos.append(
            ProductoPDS4Real(
                product_id=filename,
                sol=parsed["sol"],
                sclk=parsed["sclk"],
                camera_eye=parsed["camera_eye"],
                img_url=f"{BUNDLE_ROOT_URL}/{file_path.lstrip('/')}",
                label_url=f"{BUNDLE_ROOT_URL}/{label_path.lstrip('/')}",
                checksum_manifiesto=row.get(checksum_col) if checksum_col else None,
            )
        )
    return productos


def fetch_manifest(session=None) -> list[dict]:
    """Descarga el manifiesto una sola vez (~44 MB) y lo devuelve parseado."""
    if session is None:
        import requests

        session = requests.Session()
    response = session.get(MANIFEST_URL, timeout=60)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))


def download_and_validate(producto: ProductoPDS4Real, session=None) -> bytes:
    """
    Descarga el .IMG de un producto y valida su checksum MD5 contra el
    manifiesto. Lanza ChecksumMismatchError si no coincide -- quien llama
    decide qué hacer (FR-004: poner en cuarentena, no pasar a Silver).
    """
    if session is None:
        import requests

        session = requests.Session()
    response = session.get(producto.img_url, timeout=30)
    response.raise_for_status()
    content = response.content

    if producto.checksum_manifiesto:
        actual = hashlib.md5(content).hexdigest()
        if actual.lower() != producto.checksum_manifiesto.lower():
            raise ChecksumMismatchError(
                f"Checksum no coincide para {producto.product_id}: "
                f"manifiesto={producto.checksum_manifiesto} calculado={actual}"
            )
    return content


def upload_to_raw(producto: ProductoPDS4Real, content: bytes, client=None) -> str:
    """Sube el producto validado a la capa Raw, preservando el product_id real."""
    from rovermars_common.storage import object_store_client_from_env

    client = client or object_store_client_from_env()
    key = f"{producto.sol:04d}/{producto.product_id}.IMG"
    client.put_object(RAW_BUCKET, key, io.BytesIO(content), length=len(content))
    return key


def upsert_image_product_real(cursor, producto: ProductoPDS4Real, raw_key: str) -> None:
    """
    Inserta el producto real en image_products con origen='real'.

    Idempotente a propósito (FR-007, SC-003): ON CONFLICT (product_id) DO
    NOTHING, para que repetir la ingesta sobre el mismo subconjunto no
    duplique filas.
    """
    cursor.execute(
        """
        INSERT INTO image_products
            (product_id, file_name, sol, sclk, camera_eye,
             minio_raw_key, processing_stage, origen)
        VALUES (%s, %s, %s, %s, %s, %s, 'BRONZE', 'real')
        ON CONFLICT (product_id) DO NOTHING
        """,
        (
            producto.product_id,
            f"{producto.product_id}.IMG",
            producto.sol,
            producto.sclk,
            producto.camera_eye,
            raw_key,
        ),
    )


def quarantine_image_product_real(cursor, producto: ProductoPDS4Real, motivo: str) -> None:
    """Registra un producto que no pasó la validación de checksum (FR-004)."""
    cursor.execute(
        """
        INSERT INTO image_products
            (product_id, file_name, sol, sclk, camera_eye,
             processing_stage, quality_flag, origen)
        VALUES (%s, %s, %s, %s, %s, 'BRONZE', %s, 'real')
        ON CONFLICT (product_id) DO NOTHING
        """,
        (
            producto.product_id,
            f"{producto.product_id}.IMG",
            producto.sol,
            producto.sclk,
            producto.camera_eye,
            f"QUARANTINE:{motivo}",
        ),
    )


def ingest(sols: list[int]) -> None:
    """Orquesta el flujo completo: manifiesto -> descarga -> S3 -> Postgres."""
    import psycopg2

    logger.info("Descargando manifiesto de %s", MANIFEST_URL)
    manifest_rows = fetch_manifest()
    productos = select_bounded_subset(manifest_rows, sols)
    logger.info("Subconjunto acotado: %d productos para sols=%s", len(productos), sols)

    pg_conn = psycopg2.connect(POSTGRES_CONN)
    try:
        with pg_conn, pg_conn.cursor() as cursor:
            for producto in productos:
                try:
                    content = download_and_validate(producto)
                except ChecksumMismatchError as exc:
                    logger.warning("Cuarentena: %s", exc)
                    quarantine_image_product_real(cursor, producto, str(exc))
                    continue

                raw_key = upload_to_raw(producto, content)
                upsert_image_product_real(cursor, producto, raw_key)
                logger.info("Ingerido: %s (sol=%s, %s)", producto.product_id, producto.sol, producto.camera_eye)
    finally:
        pg_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sols",
        type=int,
        nargs="+",
        required=True,
        help="Sols reales a ingerir (acotado a 1-2 para la demo, ver spec.md)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    ingest(args.sols)


if __name__ == "__main__":
    main()
