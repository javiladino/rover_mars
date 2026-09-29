# Data Model — Pipeline de Telemetría MEDA

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29

---

## Entidades del Pipeline

```
MedaPacketRaw (MinIO)
      │  1:1
      ▼
MedaBronzeRecord (Postgres: raw.meda_bronze_records)
      │  N:1  (varios registros Bronze del mismo sol+sclk se consolidan)
      ▼
MedaSilverReading (Postgres: science.meda_silver_readings)
      │  N:1  (varias lecturas Silver del mismo sol se agregan)
      ▼
FctMedaSolSummary (Postgres via dbt: marts.fct_meda_sol_summary)
```

---

## 1. MedaPacketRaw — MinIO Object

**Bucket**: `meda-raw`  
**Clave determinista**: `{sol:04d}/{apid_hex}/{packet_id}.bin`  
Ejemplo: `0001/0xc0/a3f2b1c9d4e5f607.bin`

| Campo (metadata) | Tipo | Descripción |
|-----------------|------|-------------|
| `sol` | uint32 | Sol marciano (0–999) |
| `apid` | uint16 hex | APID del sensor (0x0C0–0x0C4) |
| `packet_id` | string | SHA-256 del payload CCSDS (primeros 16 hex chars) |
| `size_bytes` | int | Tamaño del objeto |

**Invariante**: Inmutable una vez escrito. Re-ejecuciones no sobrescriben (verificado por `stat_object` antes del PUT; si existe, se omite el write).

---

## 2. MedaBronzeRecord — `raw.meda_bronze_records`

Un registro por paquete CCSDS recibido de Kafka, independientemente del resultado de validación.

```sql
CREATE TABLE IF NOT EXISTS raw.meda_bronze_records (
    id               UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    packet_id        TEXT        UNIQUE NOT NULL,     -- SHA-256 del payload (hex)
    sol              INTEGER     NOT NULL CHECK (sol BETWEEN 0 AND 999),
    sclk             FLOAT8      NOT NULL,             -- Spacecraft Clock (segundos)
    apid             INTEGER     NOT NULL,             -- 0x0C0–0x0CF (192–207)
    sensor_type      TEXT        NOT NULL
                       CHECK (sensor_type IN ('ATS','PS','WS','UV','HS')),
    minio_raw_key    TEXT        NOT NULL,
    crc_valid        BOOLEAN     NOT NULL,
    schema_valid     BOOLEAN     NOT NULL,
    quarantine_reason TEXT,                           -- NULL si no hay cuarentena
    arrival_utc      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_size_bytes INTEGER   NOT NULL
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
```

### Reglas de validación Bronze

| Validación | Campo resultante si falla | `quarantine_reason` |
|-----------|--------------------------|---------------------|
| CRC-16/CCITT del payload | `crc_valid = false` | `'crc_mismatch'` |
| APID dentro de 0x0C0–0x0CF | `schema_valid = false` | `'unknown_apid'` |
| `payload_size_bytes ≤ 65528` (límite CCSDS) | `schema_valid = false` | `'payload_too_large'` |
| Campos `sol`, `sclk`, `sensor_type` presentes | `schema_valid = false` | `'missing_fields'` |

Los registros en cuarentena (`quarantine_reason IS NOT NULL`) no se propagan a Silver.

### Estado de transición

```
RECIBIDO → crc_valid + schema_valid = true  → VALID (elegible para Silver)
         → crc_valid = false                → QUARANTINED (crc_mismatch)
         → schema_valid = false             → QUARANTINED (reason específico)
```

---

## 3. MedaSilverReading — `science.meda_silver_readings`

Consolidación calibrada de múltiples registros Bronze del mismo `(sol, sclk)`. Una fila por instante de muestreo con todos los sensores disponibles. Sensores ausentes en ese instante se persisten como NULL.

```sql
CREATE TABLE IF NOT EXISTS science.meda_silver_readings (
    id                    UUID        DEFAULT uuid_generate_v4() PRIMARY KEY,
    sol                   INTEGER     NOT NULL CHECK (sol BETWEEN 0 AND 999),
    sclk                  FLOAT8      NOT NULL,
    lmst_h                FLOAT8,                     -- Local Mean Solar Time (horas decimales)

    -- Lecturas calibradas (NULL si el sensor no reportó en este instante)
    temperature_ats_c     FLOAT4,     -- °C; rango válido: −120 a +40
    pressure_hpa          FLOAT4,     -- hPa; rango válido: 0 a 120
    wind_speed_ms         FLOAT4,     -- m/s; rango válido: 0 a 100
    wind_direction_deg    FLOAT4,     -- °; rango válido: 0 a 360
    uv_irradiance_w_m2    FLOAT4,     -- W/m²; rango válido: 0 a 10
    humidity_pct          FLOAT4,     -- %; rango válido: 0 a 100

    -- Cobertura de sensores (true si el sensor reportó en este instante)
    has_ats               BOOLEAN     NOT NULL DEFAULT false,
    has_ps                BOOLEAN     NOT NULL DEFAULT false,
    has_ws                BOOLEAN     NOT NULL DEFAULT false,
    has_uv                BOOLEAN     NOT NULL DEFAULT false,
    has_hs                BOOLEAN     NOT NULL DEFAULT false,

    -- Anomalías
    anomaly_flag          BOOLEAN     NOT NULL DEFAULT false,
    anomaly_reason        TEXT,                        -- NULL si no hay anomalía

    -- Geoespacial (PostGIS, EPSG:4326)
    rover_location        GEOMETRY(Point, 4326),       -- posición del rover al momento

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
```

### Reglas de calibración Silver

Aplica sobre registros Bronze con `quarantine_reason IS NULL`:

| Sensor | Ecuación | Referencia |
|--------|----------|------------|
| ATS | `T_c = DN × 0.05 − 120.0` | Sebastián et al. 2021, simplificación lineal declarada |
| PS | `P_hpa = DN × 0.0293` | Sebastián et al. 2021, simplificación lineal declarada |
| WS speed | `v = DN × 0.0244` | Sebastián et al. 2021, simplificación lineal declarada |
| WS dir | `d = DN × 0.0879` | Idem |
| UV | `irr = DN × 0.00244` | Sebastián et al. 2021, simplificación lineal declarada |
| HS | `h = DN × 0.0244` | Sebastián et al. 2021, simplificación lineal declarada |

### Regla de anomalía Silver

| Condición | `anomaly_flag` | `anomaly_reason` |
|-----------|---------------|-----------------|
| `temperature_ats_c` fuera de [−120, +40] | `true` | `'temp_out_of_range'` |
| `pressure_hpa` fuera de [0, 120] | `true` | `'pressure_out_of_range'` |
| `wind_speed_ms ≥ 20.0` | `true` | `'dust_storm_wind'` |
| `uv_irradiance_w_m2` fuera de [0, 10] | `true` | `'uv_out_of_range'` |
| `humidity_pct` fuera de [0, 100] | `true` | `'humidity_out_of_range'` |

### Upsert Silver

```sql
INSERT INTO science.meda_silver_readings (...) VALUES (...)
ON CONFLICT (sol, sclk) DO UPDATE SET
    temperature_ats_c  = EXCLUDED.temperature_ats_c,
    pressure_hpa       = EXCLUDED.pressure_hpa,
    -- ... todos los campos calibrados
    updated_at         = NOW();
```

---

## 4. FctMedaSolSummary — dbt mart

**Modelo dbt**: `dbt/models/marts/fct_meda_sol_summary.sql`  
**Fuente**: `science.meda_silver_readings` (via `ref('stg_meda_silver')`)

```
fct_meda_sol_summary
├── sol                INTEGER  PK — not_null, unique
├── temp_min_c         FLOAT4   — not_null, accepted_range: [-120, 40]
├── temp_max_c         FLOAT4   — not_null, accepted_range: [-120, 40]
├── temp_avg_c         FLOAT4   — not_null, accepted_range: [-120, 40]
├── pressure_avg_hpa   FLOAT4   — not_null, accepted_range: [0, 120]
├── wind_speed_max_ms  FLOAT4   — not_null, accepted_range: [0, 100]
├── uv_dose_wh_m2      FLOAT4   — not_null, accepted_range: [0, 240]
├── reading_count      INTEGER  — not_null, value: > 0
└── anomaly_count      INTEGER  — not_null, value: >= 0
```

**Tests declarativos dbt** (en `_marts__models.yml`):
- `not_null` en todos los campos
- `unique` en `sol`
- `accepted_range` para todos los campos físicos (rangos de la tabla anterior)
- `expression_is_true`: `temp_min_c <= temp_avg_c AND temp_avg_c <= temp_max_c`

---

## 5. Dimensión Reutilizada

**`dim_dsn_stations`** (ya existe): Las lecturas MEDA se reciben por el mismo enlace DSN que Mastcam-Z. No se modifica esta dimensión; el DAG MEDA la referencia como contexto de misión, no como FK directa en las tablas Bronze/Silver.

---

## 6. Relaciones Cross-Pipeline

El pipeline MEDA es **aislado** del pipeline Mastcam-Z:
- Tablas separadas (`meda_bronze_records`, `meda_silver_readings` vs `image_products`)
- Topics Kafka separados (`telemetry.meda.raw` vs `etl.bronze.ready`)
- Buckets MinIO separados (`meda-*` vs `mastcamz-*`)
- Módulos Python separados (`meda_calibration.py`, `meda_anomaly_rules.py`)

La única integración intencional es `fct_sol_summary` en dbt, que puede hacer `JOIN` a `fct_meda_sol_summary` para una vista unificada de actividad por sol — pero este JOIN es opcional y no bloquea el pipeline MEDA.
