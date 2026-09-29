"""
Tests de la matemática de calibración física MEDA (airflow/plugins/meda_calibration.py).

Cubre 100% de las funciones de calibración con al menos un caso por sensor (CE-003).
Tolerancia rel=1e-4 usada en pytest.approx para manejar aritmética de punto flotante.

Casos de referencia derivados de las ecuaciones documentadas en research.md §3
y verificados contra la especificación del instrumento (Sebastián et al. 2021).
"""

import pytest
from meda_calibration import (
    calibrate_ats,
    calibrate_hs,
    calibrate_ps,
    calibrate_uv,
    calibrate_ws_dir,
    calibrate_ws_speed,
)

# ── ATS — Air Temperature Sensor ────────────────────────────────────────────

def test_calibrate_ats_nominal():
    # DN=3200 → T_c = 3200 × 0.05 + (−120.0) = 40.0 °C
    assert calibrate_ats(3200) == pytest.approx(40.0, rel=1e-4)


def test_calibrate_ats_min():
    # DN=0 → T_c = 0 × 0.05 + (−120.0) = −120.0 °C (límite inferior ICD)
    assert calibrate_ats(0) == pytest.approx(-120.0, rel=1e-4)


def test_calibrate_ats_max():
    # DN=4095 → T_c = 4095 × 0.05 − 120.0 = 84.75 °C
    assert calibrate_ats(4095) == pytest.approx(84.75, rel=1e-4)


def test_calibrate_ats_midrange():
    # DN=2400 → T_c = 2400 × 0.05 − 120.0 = 0.0 °C
    assert calibrate_ats(2400) == pytest.approx(0.0, abs=1e-9)


# ── PS — Pressure Sensor ─────────────────────────────────────────────────────

def test_calibrate_ps_nominal():
    # DN=4095 → P_hpa = 4095 × 0.0293 ≈ 119.98 hPa (dentro de ±0.5 hPa del ICD ~120)
    result = calibrate_ps(4095)
    assert result == pytest.approx(119.9835, rel=1e-4)


def test_calibrate_ps_zero():
    # DN=0 → P_hpa = 0.0 hPa
    assert calibrate_ps(0) == pytest.approx(0.0, abs=1e-9)


def test_calibrate_ps_midrange():
    # DN=2048 → P_hpa = 2048 × 0.0293 ≈ 60.01 hPa
    assert calibrate_ps(2048) == pytest.approx(60.0064, rel=1e-4)


# ── WS — Wind Sensor (TWINS) ─────────────────────────────────────────────────

def test_calibrate_ws_speed():
    # DN=820 → v = 820 × 0.0244 ≈ 20.008 m/s (near dust storm threshold 20.0)
    assert calibrate_ws_speed(820) == pytest.approx(20.008, rel=1e-4)


def test_calibrate_ws_speed_zero():
    assert calibrate_ws_speed(0) == pytest.approx(0.0, abs=1e-9)


def test_calibrate_ws_dir():
    # DN=4095 → d = 4095 × 0.0879 = 359.9505°
    assert calibrate_ws_dir(4095) == pytest.approx(359.9505, rel=1e-4)


def test_calibrate_ws_dir_zero():
    assert calibrate_ws_dir(0) == pytest.approx(0.0, abs=1e-9)


# ── UV — UV Irradiance Sensor ─────────────────────────────────────────────────

def test_calibrate_uv():
    # DN=4095 → irr = 4095 × 0.00244 ≈ 9.9918 W/m²
    assert calibrate_uv(4095) == pytest.approx(9.9918, rel=1e-4)


def test_calibrate_uv_zero():
    assert calibrate_uv(0) == pytest.approx(0.0, abs=1e-9)


def test_calibrate_uv_midrange():
    # DN=2048 → irr = 2048 × 0.00244 ≈ 4.997 W/m²
    assert calibrate_uv(2048) == pytest.approx(4.99712, rel=1e-4)


# ── HS — Humidity Sensor (TEET) ───────────────────────────────────────────────

def test_calibrate_hs():
    # DN=4095 → h = 4095 × 0.0244 ≈ 99.918% (near 100% cap)
    assert calibrate_hs(4095) == pytest.approx(99.918, rel=1e-4)


def test_calibrate_hs_zero():
    assert calibrate_hs(0) == pytest.approx(0.0, abs=1e-9)


def test_calibrate_hs_midrange():
    # DN=2048 → h = 2048 × 0.0244 ≈ 49.97%
    assert calibrate_hs(2048) == pytest.approx(49.9712, rel=1e-4)
