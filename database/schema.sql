-- ============================================================
-- Rover Mars — PostgreSQL/PostGIS Schema
-- Simulates NASA JPL OPGS (Operations Product Generation Subsystem)
-- data model for Mars 2020 Perseverance image and telemetry products.
-- ============================================================

\connect rover_mars

-- ─── SCHEMAS ────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS raw;       -- Mirrors Bronze layer
CREATE SCHEMA IF NOT EXISTS science;   -- Silver & Gold calibrated data
CREATE SCHEMA IF NOT EXISTS mission;   -- Mission planning & context
CREATE SCHEMA IF NOT EXISTS monitoring;-- Pipeline health & metrics

-- ============================================================
-- TABLE: image_products
-- Core catalog of all Mastcam-Z image products.
-- Each row = one EDR/RDR image file.
-- ============================================================
CREATE TABLE IF NOT EXISTS image_products (
    id                    UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    product_id            TEXT        UNIQUE NOT NULL,          -- PDS4 logical identifier
    file_name             TEXT        NOT NULL,                 -- e.g. M20_MCZL_0001_0000123456_000.IMG
    sol                   INTEGER     NOT NULL CHECK (sol >= 0),
    sclk                  FLOAT8,                               -- Spacecraft clock (seconds)

    -- Camera parameters
    camera_eye            TEXT        CHECK (camera_eye IN ('LEFT', 'RIGHT')),
    filter_wavelength_nm  INTEGER     CHECK (filter_wavelength_nm BETWEEN 400 AND 1100),
    focal_mm              FLOAT4      CHECK (focal_mm BETWEEN 26 AND 110),
    exposure_ms           FLOAT4,
    horizontal_fov_deg    FLOAT4,
    vertical_fov_deg      FLOAT4,
    pixel_scale_mrad_px   FLOAT4,

    -- Transmission metadata
    dsn_station           TEXT,                                 -- Goldstone | Madrid | Canberra
    light_delay_s         FLOAT4,                              -- One-way light travel time
    n_ccsds_packets       INTEGER,

    -- Timing
    capture_utc           TIMESTAMPTZ,
    arrival_utc           TIMESTAMPTZ,
    ingestion_utc         TIMESTAMPTZ DEFAULT NOW(),

    -- Processing pipeline
    product_type          TEXT,                                 -- EBB | ERG | ERZ | EZT | ENB
    processing_stage      TEXT        DEFAULT 'BRONZE',
    quality_flag          TEXT        DEFAULT 'GOOD',

    -- MinIO storage keys (Medallion layers)
    minio_raw_key         TEXT,
    minio_bronze_key      TEXT,
    minio_silver_key      TEXT,
    minio_gold_key        TEXT,
    pds4_xml_key          TEXT,

    -- Geospatial (Mars planetocentric, EPSG:4326 reprojected for PostGIS)
    rover_location        GEOMETRY(Point, 4326),
    image_footprint       GEOMETRY(Polygon, 4326),

    -- Calibration metrics
    radiometric_factor    FLOAT4,
    dust_opacity_tau      FLOAT4,
    solar_longitude_deg   FLOAT4,

    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ip_sol          ON image_products (sol);
CREATE INDEX IF NOT EXISTS idx_ip_camera_eye   ON image_products (camera_eye);
CREATE INDEX IF NOT EXISTS idx_ip_filter_wl    ON image_products (filter_wavelength_nm);
CREATE INDEX IF NOT EXISTS idx_ip_stage        ON image_products (processing_stage);
CREATE INDEX IF NOT EXISTS idx_ip_capture_utc  ON image_products (capture_utc);
CREATE INDEX IF NOT EXISTS idx_ip_location     ON image_products USING GIST (rover_location);
CREATE INDEX IF NOT EXISTS idx_ip_footprint    ON image_products USING GIST (image_footprint);
CREATE INDEX IF NOT EXISTS idx_ip_product_id   ON image_products USING GIN  (product_id gin_trgm_ops);

-- ============================================================
-- TABLE: telemetry_records
-- MEDA-equivalent sensor data per sol/LMST
-- ============================================================
CREATE TABLE IF NOT EXISTS telemetry_records (
    id                    UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    sol                   INTEGER     NOT NULL,
    local_mean_solar_time FLOAT4,
    utc_timestamp         TIMESTAMPTZ DEFAULT NOW(),

    -- Position
    latitude_deg          FLOAT8,
    longitude_deg         FLOAT8,
    altitude_m            FLOAT4,
    heading_deg           FLOAT4,
    rover_location        GEOMETRY(Point, 4326),
    wheel_odometry_m      FLOAT4,

    -- Environment (MEDA instruments)
    surface_temp_c        FLOAT4,
    air_temp_1m_c         FLOAT4,
    atm_pressure_pa       FLOAT4,
    wind_speed_ms         FLOAT4,
    wind_direction_deg    FLOAT4,
    uv_index              FLOAT4,
    dust_opacity_tau      FLOAT4,

    -- Power (MMRTG)
    battery_pct           FLOAT4,
    power_consumed_w      FLOAT4,
    mmrtg_output_w        FLOAT4,

    -- Communications
    earth_mars_dist_mkm   FLOAT4,
    light_travel_time_s   FLOAT4,
    uhf_link_active       BOOLEAN,
    data_volume_mbit_sol  FLOAT4,

    -- Activities
    arm_deployed          BOOLEAN,
    sample_count          INTEGER
);

CREATE INDEX IF NOT EXISTS idx_tel_sol      ON telemetry_records (sol);
CREATE INDEX IF NOT EXISTS idx_tel_utc      ON telemetry_records (utc_timestamp);
CREATE INDEX IF NOT EXISTS idx_tel_location ON telemetry_records USING GIST (rover_location);
CREATE INDEX IF NOT EXISTS idx_tel_temp     ON telemetry_records (surface_temp_c);
CREATE INDEX IF NOT EXISTS idx_tel_pressure ON telemetry_records (atm_pressure_pa);

-- ============================================================
-- TABLE: sol_summaries
-- Gold layer: daily aggregated statistics per sol
-- ============================================================
CREATE TABLE IF NOT EXISTS sol_summaries (
    sol                   INTEGER     PRIMARY KEY,
    n_images_total        INTEGER     DEFAULT 0,
    n_images_left         INTEGER     DEFAULT 0,
    n_images_right        INTEGER     DEFAULT 0,
    n_filters_used        INTEGER     DEFAULT 0,
    data_volume_mbit      FLOAT4,
    avg_surface_temp_c    FLOAT4,
    min_surface_temp_c    FLOAT4,
    max_surface_temp_c    FLOAT4,
    avg_pressure_pa       FLOAT4,
    avg_dust_opacity_tau  FLOAT4,
    max_dust_opacity_tau  FLOAT4,
    dust_storm_flag       BOOLEAN     DEFAULT FALSE,
    total_drive_m         FLOAT4,
    battery_min_pct       FLOAT4,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE: pipeline_metrics
-- ETL performance monitoring
-- ============================================================
CREATE TABLE IF NOT EXISTS monitoring.pipeline_metrics (
    id                    SERIAL      PRIMARY KEY,
    run_id                TEXT        NOT NULL,
    dag_id                TEXT,
    task_id               TEXT,
    sol                   INTEGER,
    n_products_processed  INTEGER,
    n_errors              INTEGER     DEFAULT 0,
    processing_time_s     FLOAT4,
    stage                 TEXT,
    run_at                TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- VIEWS — Science team analytics
-- ============================================================

-- View: multispectral coverage per sol
CREATE OR REPLACE VIEW science.sol_filter_coverage AS
SELECT
    sol,
    COUNT(DISTINCT filter_wavelength_nm)          AS n_filters,
    COUNT(*)                                       AS n_images,
    SUM(CASE WHEN camera_eye = 'LEFT'  THEN 1 ELSE 0 END) AS n_left,
    SUM(CASE WHEN camera_eye = 'RIGHT' THEN 1 ELSE 0 END) AS n_right,
    ARRAY_AGG(DISTINCT filter_wavelength_nm ORDER BY filter_wavelength_nm) AS filters_nm,
    MIN(capture_utc)                               AS first_capture,
    MAX(capture_utc)                               AS last_capture
FROM image_products
GROUP BY sol
ORDER BY sol;

-- View: rover traverse path
CREATE OR REPLACE VIEW science.rover_traverse AS
SELECT
    i.sol,
    i.capture_utc,
    i.rover_location,
    ST_AsGeoJSON(i.rover_location)::json           AS geojson_point,
    t.wheel_odometry_m
FROM image_products i
LEFT JOIN telemetry_records t ON i.sol = t.sol
WHERE i.rover_location IS NOT NULL
ORDER BY i.sol, i.capture_utc;

-- View: dust storm events
CREATE OR REPLACE VIEW science.dust_storm_events AS
SELECT
    sol,
    MAX(dust_opacity_tau)                          AS max_tau,
    AVG(dust_opacity_tau)                          AS avg_tau,
    COUNT(*)                                       AS n_observations,
    MIN(utc_timestamp)                             AS event_start,
    MAX(utc_timestamp)                             AS event_end
FROM telemetry_records
WHERE dust_opacity_tau > 2.0
GROUP BY sol
HAVING MAX(dust_opacity_tau) > 2.0
ORDER BY sol;

-- View: telemetry time-series for Grafana
CREATE OR REPLACE VIEW science.telemetry_timeseries AS
SELECT
    utc_timestamp          AS "time",
    sol,
    surface_temp_c         AS "Surface Temp (°C)",
    air_temp_1m_c          AS "Air Temp 1m (°C)",
    atm_pressure_pa        AS "Pressure (Pa)",
    wind_speed_ms          AS "Wind Speed (m/s)",
    uv_index               AS "UV Index",
    dust_opacity_tau       AS "Dust Opacity τ",
    battery_pct            AS "Battery (%)",
    mmrtg_output_w         AS "MMRTG Output (W)",
    earth_mars_dist_mkm    AS "Earth-Mars Dist (Mkm)",
    light_travel_time_s/60 AS "Light Travel Time (min)"
FROM telemetry_records
ORDER BY utc_timestamp;

-- ============================================================
-- FUNCTION: auto-update updated_at timestamp
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_image_products_updated_at
    BEFORE UPDATE ON image_products
    FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- ============================================================
-- FUNCTION: compute image footprint polygon
-- Given rover position, camera FOV and altitude, computes
-- the approximate ground footprint as a PostGIS polygon.
-- ============================================================
CREATE OR REPLACE FUNCTION compute_image_footprint(
    rover_lat FLOAT8,
    rover_lon FLOAT8,
    altitude_m FLOAT4,
    hfov_deg FLOAT4,
    vfov_deg FLOAT4,
    heading_deg FLOAT4 DEFAULT 0
)
RETURNS GEOMETRY AS $$
DECLARE
    -- Ground distance from nadir per half-FOV
    half_w_m FLOAT8 := altitude_m * TAN(RADIANS(hfov_deg / 2));
    half_h_m FLOAT8 := altitude_m * TAN(RADIANS(vfov_deg / 2));
    deg_per_m FLOAT8 := 1.0 / 111000.0;
    half_w_deg FLOAT8 := half_w_m * deg_per_m;
    half_h_deg FLOAT8 := half_h_m * deg_per_m;
BEGIN
    RETURN ST_SetSRID(
        ST_MakePolygon(ST_MakeLine(ARRAY[
            ST_MakePoint(rover_lon - half_w_deg, rover_lat - half_h_deg),
            ST_MakePoint(rover_lon + half_w_deg, rover_lat - half_h_deg),
            ST_MakePoint(rover_lon + half_w_deg, rover_lat + half_h_deg),
            ST_MakePoint(rover_lon - half_w_deg, rover_lat + half_h_deg),
            ST_MakePoint(rover_lon - half_w_deg, rover_lat - half_h_deg)
        ])),
        4326
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Table for points of interest
CREATE TABLE IF NOT EXISTS mission.points_of_interest (
    id          SERIAL      PRIMARY KEY,
    name        TEXT        NOT NULL,
    location    GEOMETRY(Point, 4326),
    description TEXT,
    category    TEXT
);

-- Seed: static Jezero Crater region of interest
INSERT INTO mission.points_of_interest (name, location, description, category)
VALUES
    ('Jezero Crater Floor',  ST_SetSRID(ST_MakePoint(77.4508, 18.4447), 4326), 'Landing ellipse center', 'LANDING'),
    ('Ancient River Delta',  ST_SetSRID(ST_MakePoint(77.39,   18.48),   4326), 'Primary science target', 'SCIENCE'),
    ('Crater Rim East',      ST_SetSRID(ST_MakePoint(77.62,   18.43),   4326), 'Carbonate outcrops',    'SCIENCE'),
    ('Isidis Basin Edge',    ST_SetSRID(ST_MakePoint(77.51,   18.53),   4326), 'Olivine-bearing unit',  'SCIENCE')
ON CONFLICT DO NOTHING;
