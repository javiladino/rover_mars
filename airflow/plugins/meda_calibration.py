"""
Funciones puras de calibración física MEDA (Mars Environmental Dynamics Analyzer).

Sin dependencias de Airflow, Kafka ni Postgres — diseñadas para ser testeadas de
forma aislada con pytest (ver tests/test_meda_calibration.py) y reutilizadas fuera
del contexto de una tarea de Airflow (notebooks, análisis offline, etc.).

Ecuaciones adoptadas de Sebastián et al. (2021), "The Mars Environmental Dynamics
Analyzer, MEDA. A suite of environmental sensors for the Mars 2020 mission",
Journal of Geophysical Research: Planets, 126, e2021JE006823.
DOI: 10.1029/2021JE006823.

Simplificaciones declaradas: Los coeficientes reales de MEDA son polinomiales y
varían por subsensor (p.ej. ATS1/ATS2). Esta implementación usa conversiones
lineales con coeficientes representativos del rango de operación en Jezero Crater.
Ver research.md §3 para detalle por sensor.
"""

# ── Constantes de calibración ATS (Air Temperature Sensor) ──────────────────
GAIN_ATS = 0.05       # °C / DN
OFFSET_ATS = -120.0   # °C

# ── Constantes de calibración PS (Pressure Sensor) ───────────────────────────
GAIN_PS = 0.0293      # hPa / DN  (= 2.93 Pa/DN)

# ── Constantes de calibración WS (Wind Sensor — TWINS) ───────────────────────
GAIN_WS_SPEED = 0.0244  # m/s / DN
GAIN_WS_DIR = 0.0879    # ° / DN

# ── Constantes de calibración UV (UV Irradiance Sensor) ──────────────────────
GAIN_UV = 0.00244     # W/m² / DN

# ── Constantes de calibración HS (Humidity Sensor — TEET) ────────────────────
GAIN_HS = 0.0244      # % / DN


def calibrate_ats(dn: int) -> float:
    """Calibra un valor DN del sensor ATS a temperatura en °C.

    T_c = DN × GAIN_ATS + OFFSET_ATS
    Rango DN: 0–4095 → Rango T: −120 °C a +84.75 °C
    Rango operativo ICD: −120 °C a +40 °C
    """
    return dn * GAIN_ATS + OFFSET_ATS


def calibrate_ps(dn: int) -> float:
    """Calibra un valor DN del sensor PS a presión en hPa.

    P_hpa = DN × GAIN_PS
    Rango DN: 0–4095 → Rango P: 0–120.0 hPa (0–1200 Pa per ICD)
    """
    return dn * GAIN_PS


def calibrate_ws_speed(dn: int) -> float:
    """Calibra un valor DN de velocidad del sensor WS (TWINS) a m/s.

    v = DN × GAIN_WS_SPEED
    Rango DN: 0–4095 → Rango v: 0–100 m/s
    """
    return dn * GAIN_WS_SPEED


def calibrate_ws_dir(dn: int) -> float:
    """Calibra un valor DN de dirección del sensor WS (TWINS) a grados.

    d = DN × GAIN_WS_DIR
    Rango DN: 0–4095 → Rango d: 0–360°
    """
    return dn * GAIN_WS_DIR


def calibrate_uv(dn: int) -> float:
    """Calibra un valor DN del sensor UV a irradiancia en W/m².

    irr = DN × GAIN_UV
    Rango DN: 0–4095 → Rango irr: 0–10 W/m²
    """
    return dn * GAIN_UV


def calibrate_hs(dn: int) -> float:
    """Calibra un valor DN del sensor HS (TEET) a humedad relativa en %.

    h = DN × GAIN_HS
    Rango DN: 0–4095 → Rango h: 0–100%
    """
    return dn * GAIN_HS
