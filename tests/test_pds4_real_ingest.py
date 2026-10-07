"""
Tests de ingestion/pds4_real_ingest.py.

Ninguno de estos tests toca la red real ni una base de datos real -- el
manifiesto, la descarga y el cursor de Postgres se simulan con objetos de
prueba. Ver specs/002-aws-deployment/research.md (Decisión 2) para el
formato real de producto que estos tests fijan.
"""

from unittest.mock import MagicMock

import pytest
from pds4_real_ingest import (
    ChecksumMismatchError,
    download_and_validate,
    parse_product_filename,
    quarantine_image_product_real,
    select_bounded_subset,
    upsert_image_product_real,
)

# ── parse_product_filename ──────────────────────────────────────────────


def test_parse_product_filename_left_camera():
    result = parse_product_filename("ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03")
    assert result == {"camera_eye": "LEFT", "sol": 100, "sclk": 675828555.0}


def test_parse_product_filename_right_camera():
    result = parse_product_filename("ZR2_0100_0675835150_098IOF_N0040218ZCAM01000_026080A04")
    assert result == {"camera_eye": "RIGHT", "sol": 100, "sclk": 675835150.0}


def test_parse_product_filename_rejects_unknown_format():
    # El formato inventado del simulador (M20_MCZL_...) NO es el real --
    # ver research.md Decisión 2. No debe aceptarse silenciosamente.
    with pytest.raises(ValueError):
        parse_product_filename("M20_MCZL_0001_0000700032_000RZL_N_01")


# ── select_bounded_subset ───────────────────────────────────────────────


def test_select_bounded_subset_filters_by_sol_and_detects_columns():
    manifest_rows = [
        {
            "File Path": "data/0100/ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.IMG",
            "MD5 Checksum": "abc123",
        },
        {
            "File Path": "data/0200/ZL6_0200_0680000000_098IOF_N0040218ZCAM01000_026080A05.IMG",
            "MD5 Checksum": "def456",
        },
        {
            # No es .IMG -- debe ignorarse.
            "File Path": "data/0100/ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.xml",
            "MD5 Checksum": "xxxxxx",
        },
    ]

    productos = select_bounded_subset(manifest_rows, sols=[100])

    assert len(productos) == 1
    producto = productos[0]
    assert producto.sol == 100
    assert producto.camera_eye == "LEFT"
    assert producto.checksum_manifiesto == "abc123"
    assert producto.img_url.endswith(
        "data/0100/ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.IMG"
    )
    assert producto.label_url.endswith(
        "data/0100/ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03.xml"
    )


def test_select_bounded_subset_skips_unparseable_filenames():
    manifest_rows = [{"File Path": "data/misc/readme.IMG", "MD5 Checksum": "x"}]
    assert select_bounded_subset(manifest_rows, sols=[100]) == []


def test_select_bounded_subset_empty_manifest():
    assert select_bounded_subset([], sols=[100]) == []


# ── download_and_validate ───────────────────────────────────────────────


def _fake_session(content: bytes):
    session = MagicMock()
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    session.get.return_value = response
    return session


def test_download_and_validate_accepts_matching_checksum():
    import hashlib

    content = b"contenido de prueba"
    checksum = hashlib.md5(content).hexdigest()
    productos = select_bounded_subset(
        [{"File Path": "data/0100/ZL6_0100_0675828555_098IOF_X.IMG", "MD5 Checksum": checksum}],
        sols=[100],
    )
    producto = productos[0]

    result = download_and_validate(producto, session=_fake_session(content))
    assert result == content


def test_download_and_validate_raises_on_checksum_mismatch():
    content = b"contenido real"
    productos = select_bounded_subset(
        [{"File Path": "data/0100/ZL6_0100_0675828555_098IOF_X.IMG", "MD5 Checksum": "no-coincide"}],
        sols=[100],
    )
    producto = productos[0]

    with pytest.raises(ChecksumMismatchError):
        download_and_validate(producto, session=_fake_session(content))


# ── upsert / cuarentena (Postgres simulado) ─────────────────────────────


def test_upsert_image_product_real_marks_origen_real():
    productos = select_bounded_subset(
        [{"File Path": "data/0100/ZL6_0100_0675828555_098IOF_X.IMG", "MD5 Checksum": "abc"}],
        sols=[100],
    )
    producto = productos[0]
    cursor = MagicMock()

    upsert_image_product_real(cursor, producto, raw_key="0100/ZL6_0100_...IMG")

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "origen" in sql
    assert "'real'" in sql or "real" in params
    assert producto.product_id in params
    assert "ON CONFLICT (product_id) DO NOTHING" in sql


def test_quarantine_image_product_real_records_reason():
    productos = select_bounded_subset(
        [{"File Path": "data/0100/ZL6_0100_0675828555_098IOF_X.IMG", "MD5 Checksum": "abc"}],
        sols=[100],
    )
    producto = productos[0]
    cursor = MagicMock()

    quarantine_image_product_real(cursor, producto, motivo="checksum no coincide")

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "QUARANTINE" in params[-1]
