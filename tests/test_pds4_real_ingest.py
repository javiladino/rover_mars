"""
Tests de ingestion/pds4_real_ingest.py.

Ninguno de estos tests toca la red real ni una base de datos real -- el
listado de directorio, la etiqueta PDS4 y el cursor de Postgres se simulan
con objetos de prueba. Ver specs/002-aws-deployment/research.md (Decisión 2,
versión revisada) para el mecanismo real de descubrimiento de productos.
"""

import hashlib
from unittest.mock import MagicMock

import pytest
from pds4_real_ingest import (
    ChecksumMismatchError,
    download_and_validate,
    fetch_label_checksum,
    list_sol_products,
    parse_product_filename,
    quarantine_image_product_real,
    upsert_image_product_real,
)

# Listado de directorio real (recortado) de
# mars2020_mastcamz_ops_raw/data/sol/00100/ids/edr/zcam/ -- ver research.md.
_SOL_100_DIR_LISTING_HTML = """
<html><body>
<a href="ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.IMG">ZL6_..._026080J03.IMG</a>
<a href="ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.xml">ZL6_..._026080J03.xml</a>
<a href="ZR2_0100_0675835150_098ECM_N0040218ZCAM01000_026080J04.IMG">ZR2_..._026080J04.IMG</a>
<a href="ZR2_0100_0675835150_098ECM_N0040218ZCAM01000_026080J04.xml">ZR2_..._026080J04.xml</a>
<a href="ZL6_0100_0675828555_098EJP_N0040218ZCAM01000_026080J03.JPG">preview, debe ignorarse</a>
</body></html>
"""


def _fake_session(text: str = "", content: bytes = b""):
    session = MagicMock()
    response = MagicMock()
    response.text = text
    response.content = content
    response.raise_for_status = MagicMock()
    session.get.return_value = response
    return session


# ── parse_product_filename ──────────────────────────────────────────────


def test_parse_product_filename_left_camera():
    result = parse_product_filename("ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03")
    assert result == {"camera_eye": "LEFT", "sol": 100, "sclk": 675828555.0}


def test_parse_product_filename_right_camera():
    result = parse_product_filename("ZR2_0100_0675835150_098ECM_N0040218ZCAM01000_026080J04")
    assert result == {"camera_eye": "RIGHT", "sol": 100, "sclk": 675835150.0}


def test_parse_product_filename_rejects_unknown_format():
    # El formato inventado del simulador (M20_MCZL_...) NO es el real --
    # ver research.md Decisión 2. No debe aceptarse silenciosamente.
    with pytest.raises(ValueError):
        parse_product_filename("M20_MCZL_0001_0000700032_000RZL_N_01")


# ── list_sol_products ───────────────────────────────────────────────────


def test_list_sol_products_parses_img_links_and_ignores_previews():
    session = _fake_session(text=_SOL_100_DIR_LISTING_HTML)

    productos = list_sol_products(100, session=session)

    assert len(productos) == 2
    ids = {p.product_id for p in productos}
    assert "ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03" in ids
    assert "ZR2_0100_0675835150_098ECM_N0040218ZCAM01000_026080J04" in ids

    left = next(p for p in productos if p.camera_eye == "LEFT")
    assert left.sol == 100
    assert left.img_url.endswith(
        "data/sol/00100/ids/edr/zcam/ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.IMG"
    )
    assert left.label_url.endswith(
        "data/sol/00100/ids/edr/zcam/ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.xml"
    )


def test_list_sol_products_empty_listing():
    session = _fake_session(text="<html><body>(sin productos)</body></html>")
    assert list_sol_products(100, session=session) == []


# ── fetch_label_checksum ────────────────────────────────────────────────


def test_fetch_label_checksum_extracts_md5():
    expected_checksum = hashlib.md5(b"contenido de referencia").hexdigest()
    label_xml = f"<product><md5_checksum>{expected_checksum}</md5_checksum></product>"
    session = _fake_session(text=label_xml)

    checksum = fetch_label_checksum("http://example/label.xml", session=session)

    assert checksum == expected_checksum


def test_fetch_label_checksum_returns_none_when_absent():
    session = _fake_session(text="<product><no_checksum_here/></product>")
    assert fetch_label_checksum("http://example/label.xml", session=session) is None


# ── download_and_validate ───────────────────────────────────────────────


def _producto_de_prueba():
    productos = list_sol_products(100, session=_fake_session(text=_SOL_100_DIR_LISTING_HTML))
    return productos[0]


def test_download_and_validate_accepts_matching_checksum():
    content = b"contenido de prueba"
    checksum = hashlib.md5(content).hexdigest()
    label_xml = f"<product><md5_checksum>{checksum}</md5_checksum></product>"

    # Dos llamadas de red: primero la etiqueta (texto), después la imagen (bytes).
    session = MagicMock()
    label_response = MagicMock(text=label_xml)
    label_response.raise_for_status = MagicMock()
    img_response = MagicMock(content=content)
    img_response.raise_for_status = MagicMock()
    session.get.side_effect = [label_response, img_response]

    result = download_and_validate(_producto_de_prueba(), session=session)
    assert result == content


def test_download_and_validate_raises_on_checksum_mismatch():
    content = b"contenido real"
    label_xml = "<product><md5_checksum>00000000000000000000000000000000</md5_checksum></product>"

    session = MagicMock()
    label_response = MagicMock(text=label_xml)
    label_response.raise_for_status = MagicMock()
    img_response = MagicMock(content=content)
    img_response.raise_for_status = MagicMock()
    session.get.side_effect = [label_response, img_response]

    with pytest.raises(ChecksumMismatchError):
        download_and_validate(_producto_de_prueba(), session=session)


def test_download_and_validate_accepts_when_label_has_no_checksum():
    content = b"contenido sin checksum en la etiqueta"
    session = MagicMock()
    label_response = MagicMock(text="<product/>")
    label_response.raise_for_status = MagicMock()
    img_response = MagicMock(content=content)
    img_response.raise_for_status = MagicMock()
    session.get.side_effect = [label_response, img_response]

    result = download_and_validate(_producto_de_prueba(), session=session)
    assert result == content


# ── upsert / cuarentena (Postgres simulado) ─────────────────────────────


def test_upsert_image_product_real_marks_origen_real():
    producto = _producto_de_prueba()
    cursor = MagicMock()

    upsert_image_product_real(cursor, producto, raw_key="0100/ZL6_0100_...IMG")

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "origen" in sql
    assert "'real'" in sql
    assert producto.product_id in params
    assert "ON CONFLICT (product_id) DO NOTHING" in sql


def test_quarantine_image_product_real_records_reason():
    producto = _producto_de_prueba()
    cursor = MagicMock()

    quarantine_image_product_real(cursor, producto, motivo="checksum no coincide")

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "QUARANTINE" in params[-1]
