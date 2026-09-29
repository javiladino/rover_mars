-- ============================================================
-- Rover Mars — MEDA Pipeline Schema
-- Tablas Bronze y Silver para el pipeline de telemetría MEDA
-- (Mars Environmental Dynamics Analyzer, Mars 2020 Perseverance)
-- Referencia: Sebastián et al. 2021, JGR Planets, 126, e2021JE006823
-- ============================================================

\connect rover_mars

-- Schemas ya creados en 02_schema.sql (raw, science); esta sentencia
-- es defensiva para el caso de ejecución aislada.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS science;

-- ============================================================
-- TABLE: raw.meda_bronze_records
-- Un registro por paquete CCSDS MEDA recibido de Kafka.
-- Inmutable respecto al payload; solo los campos de validación
-- se actualizan en re-ejecuciones (upsert ON CONFLICT packet_id).
-- ============================================================
CREATE TABLE IF NOT EXISTS raw.meda_bronze_records (
    id                  UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    packet_id           TEXT        UNIQUE NOT NULL,
    sol                 INTEGER     NOT NULL CHECK (sol BETWEEN 0 AND 999),
    sclk                FLOAT8      NOT NULL,
    apid                INTEGER     NOT NULL,
    sensor_type         TEXT        NOT NULL
                          CHECK (sensor_type IN ('ATS', 'PS', 'WS', 'UV', 'HS')),
    minio_raw_key       TEXT        NOT NULL,
    crc_valid           BOOLEAN     NOT NULL,
    schema_valid        BOOLEAN     NOT NULL,
    quarantine_reason   TEXT,
    arrival_utc         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_size_bytes  INTEGER     NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uidx_meda_bronze_packet_id
    ON raw.meda_bronze_records (packet_id);
CREATE INDEX IF NOT EXISTS idx_meda_bronze_sol_sclk
    ON raw.meda_bronze_records (sol, sclk);
CREATE INDEX IF NOT EXISTS idx_meda_bronze_sensor
    ON raw.meda_bronze_records (sensor_type);
CREATE INDEX IF NOT EXISTS idx_meda_bronze_quarantine
    ON raw.meda_bronze_records (quarantine_reason)
    WHERE quarantine_reason IS NOT NULL;

-- ============================================================
-- TABLE: science.meda_silver_readings
-- Consolidación calibrada de múltiples registros Bronze del
-- mismo (sol, sclk). Una fila por instante de muestreo con
-- todos los sensores disponibles; sensores ausentes → NULL.
-- ============================================================
CREATE TABLE IF NOT EXISTS science.meda_silver_readings (
    id                    UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    sol                   INTEGER     NOT NULL CHECK (sol BETWEEN 0 AND 999),
    sclk                  FLOAT8      NOT NULL,
    lmst_h                FLOAT8,

    -- Lecturas calibradas (NULL si el sensor no reportó en este instante)
    temperature_ats_c     FLOAT4,
    pressure_hpa          FLOAT4,
    wind_speed_ms         FLOAT4,
    wind_direction_deg    FLOAT4,
    uv_irradiance_w_m2    FLOAT4,
    humidity_pct          FLOAT4,

    -- Cobertura de sensores
    has_ats               BOOLEAN     NOT NULL DEFAULT false,
    has_ps                BOOLEAN     NOT NULL DEFAULT false,
    has_ws                BOOLEAN     NOT NULL DEFAULT false,
    has_uv                BOOLEAN     NOT NULL DEFAULT false,
    has_hs                BOOLEAN     NOT NULL DEFAULT false,

    -- Anomalías detectadas en Silver
    anomaly_flag          BOOLEAN     NOT NULL DEFAULT false,
    anomaly_reason        TEXT,

    -- Posición geoespacial del rover al momento de la lectura
    rover_location        GEOMETRY(Point, 4326),

    ingestion_utc         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_meda_silver_sol_sclk UNIQUE (sol, sclk)
);

CREATE INDEX IF NOT EXISTS idx_meda_silver_sol
    ON science.meda_silver_readings (sol);
CREATE INDEX IF NOT EXISTS idx_meda_silver_anomaly
    ON science.meda_silver_readings (anomaly_flag)
    WHERE anomaly_flag = true;
CREATE INDEX IF NOT EXISTS idx_meda_silver_location
    ON science.meda_silver_readings USING GIST (rover_location);
