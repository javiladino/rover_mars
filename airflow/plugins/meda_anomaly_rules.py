"""
Reglas de detección de anomalías MEDA — módulo independiente de anomaly_rules.py.

No extiende ni modifica anomaly_rules.py (RF-007, Principio III de la Constitución):
el aislamiento preserva los tests de Mastcam-Z. Sigue el mismo patrón de función pura
sin I/O, con umbrales parametrizables via os.getenv().

Referencia de rangos operativos: Sebastián et al. (2021), JGR Planets, 126, e2021JE006823.
Ver research.md §4 para la tabla completa de rangos y variables de entorno.
"""

import os

MEDA_TEMP_MIN_C = float(os.getenv("MEDA_TEMP_MIN_C", "-120.0"))
MEDA_TEMP_MAX_C = float(os.getenv("MEDA_TEMP_MAX_C", "40.0"))

MEDA_PRESSURE_MIN_HPA = float(os.getenv("MEDA_PRESSURE_MIN_HPA", "0.0"))
MEDA_PRESSURE_MAX_HPA = float(os.getenv("MEDA_PRESSURE_MAX_HPA", "120.0"))

MEDA_DUST_STORM_WIND_THRESHOLD = float(os.getenv("MEDA_DUST_STORM_WIND_THRESHOLD", "20.0"))

MEDA_UV_MIN_W_M2 = float(os.getenv("MEDA_UV_MIN_W_M2", "0.0"))
MEDA_UV_MAX_W_M2 = float(os.getenv("MEDA_UV_MAX_W_M2", "10.0"))

MEDA_HUM_MIN_PCT = float(os.getenv("MEDA_HUM_MIN_PCT", "0.0"))
MEDA_HUM_MAX_PCT = float(os.getenv("MEDA_HUM_MAX_PCT", "100.0"))


def detect_anomalies(reading: dict) -> tuple[bool, str | None]:
    """Detecta la primera anomalía en una lectura Silver de MEDA.

    Verifica los 5 sensores en orden; devuelve (True, reason) al primer match
    y (False, None) si todos los campos están dentro de rango. Campos con valor
    None (sensor ausente en ese instante) se omiten — no se clasifican como anomalía.
    """
    temp = reading.get("temperature_ats_c")
    if temp is not None and not (MEDA_TEMP_MIN_C <= temp <= MEDA_TEMP_MAX_C):
        return True, "temp_out_of_range"

    pressure = reading.get("pressure_hpa")
    if pressure is not None and not (MEDA_PRESSURE_MIN_HPA <= pressure <= MEDA_PRESSURE_MAX_HPA):
        return True, "pressure_out_of_range"

    wind = reading.get("wind_speed_ms")
    if wind is not None and wind >= MEDA_DUST_STORM_WIND_THRESHOLD:
        return True, "dust_storm_wind"

    uv = reading.get("uv_irradiance_w_m2")
    if uv is not None and not (MEDA_UV_MIN_W_M2 <= uv <= MEDA_UV_MAX_W_M2):
        return True, "uv_out_of_range"

    humidity = reading.get("humidity_pct")
    if humidity is not None and not (MEDA_HUM_MIN_PCT <= humidity <= MEDA_HUM_MAX_PCT):
        return True, "humidity_out_of_range"

    return False, None
