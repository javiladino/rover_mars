-- Staging model: calibrated MEDA Silver readings per sampling instant (sol, sclk)
-- Source: science.meda_silver_readings (populated by update_silver_postgres + detect_anomalies)
SELECT
    id,
    sol,
    sclk,
    lmst_h,
    temperature_ats_c,
    pressure_hpa,
    wind_speed_ms,
    wind_direction_deg,
    uv_irradiance_w_m2,
    humidity_pct,
    has_ats,
    has_ps,
    has_ws,
    has_uv,
    has_hs,
    anomaly_flag,
    anomaly_reason,
    ingestion_utc
FROM {{ source('science', 'meda_silver_readings') }}
