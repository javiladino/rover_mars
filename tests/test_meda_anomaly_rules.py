"""
Tests para las reglas de anomalía MEDA (airflow/plugins/meda_anomaly_rules.py).

Cubre los 5 sensores, casos de valor en frontera, sensores ausentes (None) y
override via variable de entorno. Ningún test requiere infraestructura real.
"""

from meda_anomaly_rules import detect_anomalies


def _normal_reading() -> dict:
    """Lectura con todos los sensores dentro de rango operativo."""
    return {
        "temperature_ats_c": -20.0,
        "pressure_hpa": 7.5,
        "wind_speed_ms": 5.0,
        "uv_irradiance_w_m2": 3.0,
        "humidity_pct": 50.0,
    }


def test_normal_reading():
    flag, reason = detect_anomalies(_normal_reading())
    assert flag is False
    assert reason is None


# ── ATS ──────────────────────────────────────────────────────────────────────

def test_temp_out_of_range_high():
    r = _normal_reading()
    r["temperature_ats_c"] = 45.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "temp_out_of_range"


def test_temp_out_of_range_low():
    r = _normal_reading()
    r["temperature_ats_c"] = -125.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "temp_out_of_range"


def test_temp_at_max_boundary_is_valid():
    r = _normal_reading()
    r["temperature_ats_c"] = 40.0
    flag, reason = detect_anomalies(r)
    assert flag is False


def test_temp_at_min_boundary_is_valid():
    r = _normal_reading()
    r["temperature_ats_c"] = -120.0
    flag, reason = detect_anomalies(r)
    assert flag is False


# ── PS ──────────────────────────────────────────────────────────────────────

def test_pressure_out_of_range():
    r = _normal_reading()
    r["pressure_hpa"] = 130.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "pressure_out_of_range"


def test_pressure_negative():
    r = _normal_reading()
    r["pressure_hpa"] = -1.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "pressure_out_of_range"


# ── WS ──────────────────────────────────────────────────────────────────────

def test_dust_storm_wind_at_boundary():
    # boundary is inclusive: >= 20.0 → anomaly (data-model.md)
    r = _normal_reading()
    r["wind_speed_ms"] = 20.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "dust_storm_wind"


def test_wind_just_below_threshold_is_normal():
    r = _normal_reading()
    r["wind_speed_ms"] = 19.99
    flag, reason = detect_anomalies(r)
    assert flag is False


# ── UV ──────────────────────────────────────────────────────────────────────

def test_uv_negative():
    r = _normal_reading()
    r["uv_irradiance_w_m2"] = -0.1
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "uv_out_of_range"


def test_uv_over_max():
    r = _normal_reading()
    r["uv_irradiance_w_m2"] = 10.5
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "uv_out_of_range"


# ── HS ──────────────────────────────────────────────────────────────────────

def test_humidity_over_100():
    r = _normal_reading()
    r["humidity_pct"] = 101.0
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "humidity_out_of_range"


def test_humidity_negative():
    r = _normal_reading()
    r["humidity_pct"] = -0.5
    flag, reason = detect_anomalies(r)
    assert flag is True
    assert reason == "humidity_out_of_range"


# ── Sensores ausentes ────────────────────────────────────────────────────────

def test_absent_sensor_skipped():
    # wind_speed_ms=None → no debe activar dust_storm_wind
    r = _normal_reading()
    r["wind_speed_ms"] = None
    flag, reason = detect_anomalies(r)
    assert flag is False


def test_all_sensors_absent_is_normal():
    flag, reason = detect_anomalies({})
    assert flag is False
    assert reason is None


def test_partial_reading_only_temp():
    r = {"temperature_ats_c": 30.0}
    flag, reason = detect_anomalies(r)
    assert flag is False


# ── Override via env var ─────────────────────────────────────────────────────

def test_env_override_temp_max(monkeypatch):
    monkeypatch.setenv("MEDA_TEMP_MAX_C", "30.0")
    import importlib

    import meda_anomaly_rules
    importlib.reload(meda_anomaly_rules)

    from meda_anomaly_rules import detect_anomalies as _detect
    r = _normal_reading()
    r["temperature_ats_c"] = 35.0
    flag, reason = _detect(r)
    assert flag is True
    assert reason == "temp_out_of_range"

    # Restore
    importlib.reload(meda_anomaly_rules)
