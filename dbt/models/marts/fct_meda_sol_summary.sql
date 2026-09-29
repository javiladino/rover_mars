-- Gold mart: daily environmental statistics per Martian sol from MEDA Silver readings.
-- Coexists with the Airflow build_gold_aggregates task per ADR-001 (different consumers:
-- dbt is for SQL analytics; Airflow task writes JSON for Grafana/dashboard).
SELECT
    sol,
    MIN(temperature_ats_c)          AS temp_min_c,
    MAX(temperature_ats_c)          AS temp_max_c,
    AVG(temperature_ats_c)          AS temp_avg_c,
    AVG(pressure_hpa)               AS pressure_avg_hpa,
    MAX(wind_speed_ms)              AS wind_speed_max_ms,
    AVG(uv_irradiance_w_m2) * 24.659 AS uv_dose_wh_m2,
    COUNT(*)                        AS reading_count,
    SUM(CASE WHEN anomaly_flag THEN 1 ELSE 0 END) AS anomaly_count
FROM {{ ref('stg_meda_silver') }}
GROUP BY sol
