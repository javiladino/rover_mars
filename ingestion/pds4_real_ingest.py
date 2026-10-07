"""
Ingesta acotada de productos reales de Mastcam-Z desde el archivo público PDS
de JPL (bundle "ops_raw", sin calibrar -- ver specs/002-aws-deployment/research.md,
Decisión 2) hacia la capa Raw local del proyecto.

No es un servicio continuo ni corre dentro de un DAG: es un script de ingesta
puntual, pensado para un subconjunto chico de sols (Escenario 2 de
specs/002-aws-deployment/spec.md). El simulador sigue siendo la única fuente
del tramo CCSDS/DSN -- este script no lo reemplaza, convive con él.

Mecanismo de descubrimiento (revisado 2026-10-07 tras una corrida real
fallida -- ver research.md Decisión 2 para la versión completa de esta
historia): el manifiesto `collection_data_inventory.csv` del bundle NO
tiene encabezado ni columnas de ruta/checksum -- es un inventario PDS4
estándar de solo 2 columnas (estado de miembro + LIDVID en minúscula), sin
información suficiente para descargar. El mecanismo real es listar
directamente la carpeta del sol pedido:
    {BUNDLE_ROOT_URL}/data/sol/{sol:05d}/ids/edr/zcam/
Sigue siendo acotado (un GET por sol pedido, no un recorrido del árbol
completo de 658 sols) -- solo que el límite es "una carpeta por sol", no
"un manifiesto único".

Formato real de producto (verificado contra el archivo público):
    ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.IMG
    ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.xml
Prefijo de cámara (ZL=izquierda, ZR=derecha), sol (4 dígitos, aunque la
carpeta use 5), SCLK, resto de campos de la misión real. Distinto del
formato M20_MCZL_... que documenta el simulador, que es una convención
simplificada, no la real (ver research.md).

El checksum no viene en el manifiesto -- se lee de la etiqueta PDS4 (.xml)
de cada producto, que trae su propio <md5_checksum> oficial.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

BUNDLE_ROOT_URL = "https://planetarydata.jpl.nasa.gov/img/data/mars2020/mars2020_mastcamz_ops_raw"

POSTGRES_CONN = os.getenv(
    "POSTGRES_CONN", "postgresql://rover:rover2024@localhost:5432/rover_mars"
)
RAW_BUCKET = os.getenv("S3_BUCKET_RAW", "mastcamz-raw")

# Prefijo de cámara real -- ver docstring del módulo.
_CAMERA_PREFIX_TO_EYE = {"ZL": "LEFT", "ZR": "RIGHT"}

_FILENAME_RE = re.compile(r"^(?P<camera>Z[LR])\w?_(?P<sol>\d{4})_(?P<sclk>\d+)_.+$")
_IMG_HREF_RE = re.compile(r'href="([^"]+\.IMG)"', re.IGNORECASE)
_MD5_LABEL_RE = re.compile(r"<md5_checksum>\s*([a-fA-F0-9]{32})\s*</md5_checksum>")


@dataclass(frozen=True)
class ProductoPDS4Real:
    """Un producto real identificado en la carpeta de su sol -- ver data-model.md."""

    product_id: str  # nombre de archivo sin extensión
    sol: int
    sclk: float
    camera_eye: str  # "LEFT" | "RIGHT"
    img_url: str
    label_url: str


class ChecksumMismatchError(ValueError):
    """El contenido descargado no coincide con el checksum de la etiqueta PDS4 (FR-004)."""


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


def _sol_zcam_dir_url(sol: int) -> str:
    """La carpeta real de un sol en el bundle ops_raw -- ver docstring del módulo."""
    return f"{BUNDLE_ROOT_URL}/data/sol/{sol:05d}/ids/edr/zcam/"


def list_sol_products(sol: int, session=None) -> list[ProductoPDS4Real]:
    """
    Lista los productos .IMG reales de un sol pidiendo un único listado de
    directorio (ver research.md, Decisión 2 revisada).
    """
    if session is None:
        import requests

        session = requests.Session()

    dir_url = _sol_zcam_dir_url(sol)
    response = session.get(dir_url, timeout=30)
    response.raise_for_status()

    productos: list[ProductoPDS4Real] = []
    for href in _IMG_HREF_RE.findall(response.text):
        filename = PurePosixPath(href).stem
        try:
            parsed = parse_product_filename(filename)
        except ValueError:
            continue
        if parsed["sol"] != sol:
            continue
        productos.append(
            ProductoPDS4Real(
                product_id=filename,
                sol=parsed["sol"],
                sclk=parsed["sclk"],
                camera_eye=parsed["camera_eye"],
                img_url=f"{dir_url}{filename}.IMG",
                label_url=f"{dir_url}{filename}.xml",
            )
        )
    return productos


def select_bounded_subset(sols: list[int], session=None) -> list[ProductoPDS4Real]:
    """
    Reúne los productos reales de un subconjunto acotado de sols (FR del
    Escenario 2 de spec.md). Un GET por sol pedido -- no recorre el árbol
    completo del archivo.
    """
    productos: list[ProductoPDS4Real] = []
    for sol in sols:
        productos.extend(list_sol_products(sol, session=session))
    return productos


def fetch_label_checksum(label_url: str, session=None) -> str | None:
    """Lee el checksum MD5 oficial de la etiqueta PDS4 (.xml) de un producto."""
    if session is None:
        import requests

        session = requests.Session()
    response = session.get(label_url, timeout=30)
    response.raise_for_status()
    match = _MD5_LABEL_RE.search(response.text)
    return match.group(1) if match else None


def download_and_validate(producto: ProductoPDS4Real, session=None) -> bytes:
    """
    Descarga el .IMG de un producto y valida su checksum MD5 contra el de su
    etiqueta PDS4. Lanza ChecksumMismatchError si no coincide -- quien llama
    decide qué hacer (FR-004: poner en cuarentena, no pasar a Silver). Si la
    etiqueta no trae checksum reconocible, se acepta el producto igual pero
    se deja constancia en el log (no se inventa una validación que no existe).
    """
    if session is None:
        import requests

        session = requests.Session()

    checksum_esperado = fetch_label_checksum(producto.label_url, session=session)

    response = session.get(producto.img_url, timeout=30)
    response.raise_for_status()
    content = response.content

    if checksum_esperado:
        actual = hashlib.md5(content).hexdigest()
        if actual.lower() != checksum_esperado.lower():
            raise ChecksumMismatchError(
                f"Checksum no coincide para {producto.product_id}: "
                f"etiqueta={checksum_esperado} calculado={actual}"
            )
    else:
        logger.warning(
            "Etiqueta PDS4 de %s sin <md5_checksum> reconocible -- aceptado sin validar",
            producto.product_id,
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
    """Orquesta el flujo completo: listado por sol -> descarga -> S3 -> Postgres."""
    import psycopg2

    productos = select_bounded_subset(sols)
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
                logger.info(
                    "Ingerido: %s (sol=%s, %s)", producto.product_id, producto.sol, producto.camera_eye
                )
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
