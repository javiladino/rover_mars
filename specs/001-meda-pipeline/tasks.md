---
description: "Task list for Pipeline de Telemetría MEDA — extensión Medallion"
---

# Tasks: Pipeline de Telemetría MEDA

**Input**: Design documents from `/specs/001-meda-pipeline/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Incluidos — CE-003 (100% cobertura calibración) y CE-004 (dbt en verde) los requieren explícitamente.

**Organization**: Tareas agrupadas por user story para implementación y validación independiente de cada escenario.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Puede correr en paralelo (archivos diferentes, sin dependencias)
- **[Story]**: User story al que pertenece la tarea (US1–US4)
- Rutas siguen la estructura del plan.md (extensión de repo único)

## Path Conventions

Extensión del proyecto único existente — archivos nuevos en:
- `simulator/`, `airflow/dags/`, `airflow/plugins/`, `database/`, `dbt/models/`, `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Actualizar la infraestructura compartida para soportar el subsistema MEDA. Ambas tareas tocan archivos distintos y pueden completarse en paralelo.

- [ ] T001 [P] Update `docker-compose.yml` — add MinIO bucket definitions: meda-raw, meda-bronze, meda-silver, meda-gold (same `mc mb` pattern as existing mastcamz-* buckets); add Kafka topic `telemetry.meda.raw` with 5 partitions and 7-day retention (same pattern as existing `etl.bronze.ready` topic declaration)
- [ ] T002 [P] Create `database/meda_schema.sql` — CREATE SCHEMA IF NOT EXISTS raw; CREATE SCHEMA IF NOT EXISTS science; CREATE EXTENSION IF NOT EXISTS postgis; CREATE TABLE IF NOT EXISTS raw.meda_bronze_records (id UUID DEFAULT uuid_generate_v4() PRIMARY KEY, packet_id TEXT UNIQUE NOT NULL, sol INTEGER NOT NULL CHECK (sol BETWEEN 0 AND 999), sclk FLOAT8 NOT NULL, apid INTEGER NOT NULL, sensor_type TEXT NOT NULL CHECK (sensor_type IN ('ATS','PS','WS','UV','HS')), minio_raw_key TEXT NOT NULL, crc_valid BOOLEAN NOT NULL, schema_valid BOOLEAN NOT NULL, quarantine_reason TEXT, arrival_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(), payload_size_bytes INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS science.meda_silver_readings (id UUID DEFAULT uuid_generate_v4() PRIMARY KEY, sol INTEGER NOT NULL CHECK (sol BETWEEN 0 AND 999), sclk FLOAT8 NOT NULL, lmst_h FLOAT8, temperature_ats_c FLOAT4, pressure_hpa FLOAT4, wind_speed_ms FLOAT4, wind_direction_deg FLOAT4, uv_irradiance_w_m2 FLOAT4, humidity_pct FLOAT4, has_ats BOOLEAN NOT NULL DEFAULT false, has_ps BOOLEAN NOT NULL DEFAULT false, has_ws BOOLEAN NOT NULL DEFAULT false, has_uv BOOLEAN NOT NULL DEFAULT false, has_hs BOOLEAN NOT NULL DEFAULT false, anomaly_flag BOOLEAN NOT NULL DEFAULT false, anomaly_reason TEXT, rover_location GEOMETRY(Point,4326), ingestion_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), CONSTRAINT uq_meda_silver_sol_sclk UNIQUE (sol, sclk)); all 7 indexes per data-model.md (uidx_meda_bronze_packet_id, idx_meda_bronze_sol_sclk, idx_meda_bronze_sensor, idx_meda_bronze_quarantine, idx_meda_silver_sol, idx_meda_silver_anomaly, idx_meda_silver_location USING GIST)

**Checkpoint**: Infrastructure ready — code implementation can begin in parallel

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Módulos de lógica pura (sin I/O) y sus tests. Deben completarse antes de implementar las tareas del DAG que los usan. Las 4 tareas tocan archivos distintos y pueden correr en paralelo.

**⚠️ CRITICAL**: No user story work on the DAG can begin until T003 and T004 are complete (calibrate_silver and detect_anomalies import them).

- [ ] T003 [P] Create `airflow/plugins/meda_calibration.py` — 6 pure calibration functions (no I/O, no Airflow/Kafka/Postgres imports, Constitución III): calibrate_ats(dn: int) -> float using T_c = DN × GAIN_ATS + OFFSET_ATS (GAIN_ATS=0.05 °C/DN, OFFSET_ATS=−120.0 °C); calibrate_ps(dn: int) -> float using P_hpa = DN × GAIN_PS (GAIN_PS=0.0293 hPa/DN); calibrate_ws_speed(dn: int) -> float using v = DN × GAIN_WS_SPEED (GAIN_WS_SPEED=0.0244 m/s/DN); calibrate_ws_dir(dn: int) -> float using d = DN × GAIN_WS_DIR (GAIN_WS_DIR=0.0879 °/DN); calibrate_uv(dn: int) -> float using irr = DN × GAIN_UV (GAIN_UV=0.00244 W/m²/DN); calibrate_hs(dn: int) -> float using h = DN × GAIN_HS (GAIN_HS=0.0244 %/DN); all constants as module-level named variables per research.md §3; add simplification docstring citing Sebastián et al. 2021
- [ ] T004 [P] Create `airflow/plugins/meda_anomaly_rules.py` — function detect_anomalies(reading: dict) -> tuple[bool, str | None] checking all 5 sensor rules: 'temp_out_of_range' if temperature_ats_c not in [MEDA_TEMP_MIN_C, MEDA_TEMP_MAX_C] (defaults −120.0, 40.0); 'pressure_out_of_range' if pressure_hpa not in [MEDA_PRESSURE_MIN_HPA, MEDA_PRESSURE_MAX_HPA] (defaults 0.0, 120.0); 'dust_storm_wind' if wind_speed_ms >= MEDA_DUST_STORM_WIND_THRESHOLD (default 20.0); 'uv_out_of_range' if uv_irradiance_w_m2 not in [MEDA_UV_MIN_W_M2, MEDA_UV_MAX_W_M2] (defaults 0.0, 10.0); 'humidity_out_of_range' if humidity_pct not in [MEDA_HUM_MIN_PCT, MEDA_HUM_MAX_PCT] (defaults 0.0, 100.0); all 10 threshold values read via os.getenv() with float() cast and the defaults above; skip check for fields that are None (sensor absent); return (True, reason_str) on first match, (False, None) if all pass; pattern mirrors anomaly_rules.py without extending it (RF-007)
- [ ] T005 [P] Write `tests/test_meda_calibration.py` — 100% function coverage per CE-003, at least 1 test per sensor: test_calibrate_ats_nominal: DN=3200 → T_c=40.0°C (within ±0.1°C per spec EA-2.1); test_calibrate_ats_min: DN=0 → T_c=−120.0°C; test_calibrate_ats_max: DN=4095 → T_c≈84.75°C; test_calibrate_ps_nominal: DN=4095 → P_hpa≈120.0hPa (within ±0.5hPa per spec EA-2.2); test_calibrate_ps_zero: DN=0 → P_hpa=0.0; test_calibrate_ws_speed: DN=820 → v≈20.01 m/s (dust storm boundary); test_calibrate_ws_dir: DN=4095 → d≈360.1°; test_calibrate_uv: DN=4095 → irr≈9.99 W/m²; test_calibrate_hs: DN=4095 → h≈100.0%; use pytest.approx with rel=1e-4 tolerance; no external imports needed
- [ ] T006 [P] Write `tests/test_meda_anomaly_rules.py` — test_normal_reading: all sensors within range → (False, None); test_temp_out_of_range_high: temperature_ats_c=45.0 → (True, 'temp_out_of_range'); test_temp_out_of_range_low: temperature_ats_c=−125.0 → (True, 'temp_out_of_range'); test_pressure_out_of_range: pressure_hpa=130.0 → (True, 'pressure_out_of_range'); test_dust_storm_wind_at_boundary: wind_speed_ms=20.0 → (True, 'dust_storm_wind') (boundary is inclusive per data-model.md '≥ 20.0'); test_uv_negative: uv_irradiance_w_m2=−0.1 → (True, 'uv_out_of_range'); test_humidity_over_100: humidity_pct=101.0 → (True, 'humidity_out_of_range'); test_absent_sensor_skipped: reading with wind_speed_ms=None → no dust_storm_wind flag; test_env_override: monkeypatch MEDA_TEMP_MAX_C=30.0, temperature_ats_c=35.0 → (True, 'temp_out_of_range')

**Checkpoint**: Pure modules + tests complete — DAG implementation can begin

---

## Phase 3: User Story 1 — Ingestión y validación Bronze (Priority: P1) 🎯 MVP

**Goal**: Paquetes CCSDS de MEDA fluyen de Kafka a MinIO Raw (inmutable) y Postgres Bronze (validados), sin pérdida ni mutación del payload original.

**Independent Test**: Ejecutar `meda_simulator.py --seed 42 --sols 1`; trigger DAG `meda_full_pipeline`; verificar objetos en `meda-raw/{0001}/{0xc0}/...` en MinIO y filas en `raw.meda_bronze_records` con `crc_valid=true, quarantine_reason IS NULL` (quickstart.md §Escenario 1).

- [ ] T007 [US1] Create `airflow/dags/meda_pipeline.py` — DAG definition: dag_id='meda_full_pipeline', default_args={owner:'rover', retries:2, retry_delay:timedelta(minutes=1)}, schedule=None, catchup=False, tags=['meda','pipeline']; import meda_calibration and meda_anomaly_rules from airflow/plugins; import kafka_offsets from airflow/plugins; define 11 PythonOperator task stubs with dependency chain: poll_meda_queue >> ingest_raw >> validate_bronze >> calibrate_silver >> write_silver_minio >> update_silver_postgres >> detect_anomalies >> build_gold_aggregates >> dbt_build >> commit_kafka_offsets >> notify; stubs raise NotImplementedError until implemented in subsequent tasks
- [ ] T008 [P] [US1] Implement `poll_meda_queue` task in `airflow/dags/meda_pipeline.py` — connect to Consumer(KAFKA_BOOTSTRAP=os.getenv('KAFKA_BOOTSTRAP','kafka:9092'), group_id='meda_pipeline_dag', auto_offset_reset='earliest', enable_auto_commit=False); verify topic 'telemetry.meda.raw' exists in cluster metadata, raise RuntimeError('TopicNotFoundError: telemetry.meda.raw not found') if missing (no partial writes); consume up to MEDA_BATCH_SIZE (os.getenv default '100') messages with poll(timeout=30.0); decode JSON UTF-8 per kafka-topic-schema.md fields; push list to XCom key 'raw_messages'; push Consumer reference key for commit_kafka_offsets; do NOT commit offsets (RF-009)
- [ ] T009 [US1] Implement `ingest_raw` task in `airflow/dags/meda_pipeline.py` — pull XCom 'raw_messages'; for each msg: decode payload_b64 with base64.b64decode(); compute packet_id = hashlib.sha256(payload_bytes).hexdigest()[:16]; build MinIO key f"{int(msg['sol']):04d}/0x{int(msg['apid']):02x}/{packet_id}.bin"; call minio.stat_object('meda-raw', key) — if ObjectNotFound exception: call minio.put_object('meda-raw', key, BytesIO(payload_bytes), len(payload_bytes)) (else skip — Raw immutable per RF-003 and CE-002); enrich each message dict with computed packet_id and minio_raw_key; push enriched list to XCom key 'enriched_messages'
- [ ] T010 [US1] Implement `validate_bronze` task in `airflow/dags/meda_pipeline.py` — pull XCom 'enriched_messages'; for each msg compute: (1) crc_valid: decode payload_b64, compute crc16_ccitt over packet-without-last-2-bytes per contracts/ccsds-secondary-header-meda.md, compare to crc_computed field; (2) if apid not in range [192, 207]: schema_valid=False, quarantine_reason='unknown_apid'; (3) elif payload_size_bytes > 65528: schema_valid=False, quarantine_reason='payload_too_large'; (4) elif missing sol|sclk|sensor_type: schema_valid=False, quarantine_reason='missing_fields'; (5) else schema_valid=True; upsert raw.meda_bronze_records ON CONFLICT (packet_id) DO UPDATE SET crc_valid=EXCLUDED.crc_valid, schema_valid=EXCLUDED.schema_valid, quarantine_reason=EXCLUDED.quarantine_reason, minio_raw_key=EXCLUDED.minio_raw_key, payload_size_bytes=EXCLUDED.payload_size_bytes; push validated records list to XCom key 'bronze_records'

**Checkpoint**: US1 complete — paquetes ingestados y validados en Bronze. Testeable de forma independiente con quickstart.md §Escenario 1–3.

---

## Phase 4: User Story 2 — Calibración física a unidades SI (Priority: P1)

**Goal**: Lecturas Bronze válidas calibradas a unidades físicas (°C, hPa, m/s, W/m², %) consolidadas en Silver con detección de anomalías MEDA.

**Independent Test**: Dado un conjunto de registros Bronze sintéticos en Postgres con DN conocidos, ejecutar el DAG y verificar `science.meda_silver_readings` con `temperature_ats_c` ≈ DN×0.05−120.0 (±0.1°C), `crc_valid=true` registros consolidados por `(sol, sclk)`, y filas con `anomaly_flag=true` para valores fuera de rango (quickstart.md §Escenario 2 y 4).

- [ ] T011 [US2] Implement `calibrate_silver` task in `airflow/dags/meda_pipeline.py` — pull XCom 'bronze_records'; filter WHERE quarantine_reason IS NULL; group records by (sol, sclk) using defaultdict; for each (sol, sclk) group: build Silver dict initializing all calibrated fields to None and has_* to False; for each Bronze record in group: dispatch by sensor_type to meda_calibration.calibrate_ats/calibrate_ps/calibrate_ws_speed+calibrate_ws_dir/calibrate_uv/calibrate_hs; set corresponding has_* flag True; compute lmst_h = (sclk % (24.659 * 3600)) / 3600.0; query rover trajectory table for nearest sclk to get rover_lon, rover_lat; set anomaly_flag=False initially; push list of Silver dicts to XCom key 'silver_rows'
- [ ] T012 [US2] Implement `write_silver_minio` task in `airflow/dags/meda_pipeline.py` — pull XCom 'silver_rows'; for each Silver row: serialize to JSON (json.dumps, ensure NaN→null); build key f"{int(row['sol']):04d}/{row['sclk']:.3f}.json"; call minio.put_object('meda-silver', key, BytesIO(json_bytes), len(json_bytes)) with content_type='application/json' (Silver is not raw-immutable; overwrite on re-run is acceptable for idempotence)
- [ ] T013 [US2] Implement `update_silver_postgres` task in `airflow/dags/meda_pipeline.py` — pull XCom 'silver_rows'; for each row: upsert science.meda_silver_readings (all calibrated fields + has_* flags + rover_location as ST_SetSRID(ST_MakePoint(rover_lon, rover_lat), 4326)::geometry when lat/lon not None) ON CONFLICT (sol, sclk) DO UPDATE SET temperature_ats_c=EXCLUDED.temperature_ats_c, pressure_hpa=EXCLUDED.pressure_hpa, wind_speed_ms=EXCLUDED.wind_speed_ms, wind_direction_deg=EXCLUDED.wind_direction_deg, uv_irradiance_w_m2=EXCLUDED.uv_irradiance_w_m2, humidity_pct=EXCLUDED.humidity_pct, has_ats=EXCLUDED.has_ats, has_ps=EXCLUDED.has_ps, has_ws=EXCLUDED.has_ws, has_uv=EXCLUDED.has_uv, has_hs=EXCLUDED.has_hs, anomaly_flag=EXCLUDED.anomaly_flag, anomaly_reason=EXCLUDED.anomaly_reason, rover_location=EXCLUDED.rover_location, updated_at=NOW(); push updated sol list to XCom key 'processed_sols'
- [ ] T014 [US2] Implement `detect_anomalies` task in `airflow/dags/meda_pipeline.py` — pull XCom 'silver_rows'; for each row call meda_anomaly_rules.detect_anomalies(row) → (flag, reason); UPDATE science.meda_silver_readings SET anomaly_flag=%(flag)s, anomaly_reason=%(reason)s WHERE sol=%(sol)s AND sclk=%(sclk)s; push count of anomalous rows to XCom key 'anomaly_count'

**Checkpoint**: US2 complete — Silver calibrado con anomalías detectadas. Testeable con quickstart.md §Escenario 4 y suite pytest tests/test_meda_calibration.py, tests/test_meda_anomaly_rules.py.

---

## Phase 5: User Story 3 — Agregados Gold y modelos dbt (Priority: P2)

**Goal**: Analistas pueden consultar estadísticas ambientales diarias por sol desde `marts.fct_meda_sol_summary` con `dbt build` en verde.

**Independent Test**: Insertar Silver rows sintéticas directamente en Postgres para sol=100; ejecutar `dbt build --select fct_meda_sol_summary`; verificar exactamente 1 fila con sol=100, campos no nulos, `temp_min_c <= temp_avg_c <= temp_max_c`, tests declarativos en verde (quickstart.md §Escenario 5).

- [ ] T015 [US3] Implement `build_gold_aggregates` task in `airflow/dags/meda_pipeline.py` — pull XCom 'processed_sols'; for each sol in list: query SELECT sol, MIN(temperature_ats_c) temp_min_c, MAX(temperature_ats_c) temp_max_c, AVG(temperature_ats_c) temp_avg_c, AVG(pressure_hpa) pressure_avg_hpa, MAX(wind_speed_ms) wind_speed_max_ms, AVG(uv_irradiance_w_m2)*24.659 uv_dose_wh_m2, COUNT(*) reading_count, SUM(CASE WHEN anomaly_flag THEN 1 ELSE 0 END) anomaly_count FROM science.meda_silver_readings WHERE sol=%(sol)s; serialize to JSON; write to meda-gold/{sol:04d}/summary.json in MinIO (ADR-001 coexistence: dbt mart aggregates same data declaratively, this task writes JSON for Grafana/dashboard)
- [ ] T016 [P] [US3] Create `dbt/models/staging/stg_meda_bronze.sql` — SELECT id, packet_id, sol, sclk, apid, sensor_type, crc_valid, schema_valid, quarantine_reason, arrival_utc, payload_size_bytes FROM {{ source('raw', 'meda_bronze_records') }} WHERE quarantine_reason IS NULL
- [ ] T017 [P] [US3] Create `dbt/models/staging/stg_meda_silver.sql` — SELECT id, sol, sclk, lmst_h, temperature_ats_c, pressure_hpa, wind_speed_ms, wind_direction_deg, uv_irradiance_w_m2, humidity_pct, has_ats, has_ps, has_ws, has_uv, has_hs, anomaly_flag, anomaly_reason, ingestion_utc FROM {{ source('science', 'meda_silver_readings') }}
- [ ] T018 [US3] Create `dbt/models/marts/fct_meda_sol_summary.sql` — SELECT sol, MIN(temperature_ats_c) AS temp_min_c, MAX(temperature_ats_c) AS temp_max_c, AVG(temperature_ats_c) AS temp_avg_c, AVG(pressure_hpa) AS pressure_avg_hpa, MAX(wind_speed_ms) AS wind_speed_max_ms, AVG(uv_irradiance_w_m2) * 24.659 AS uv_dose_wh_m2, COUNT(*) AS reading_count, SUM(CASE WHEN anomaly_flag THEN 1 ELSE 0 END) AS anomaly_count FROM {{ ref('stg_meda_silver') }} GROUP BY sol (depends on T017 for ref)
- [ ] T019 [P] [US3] Update `dbt/models/staging/_staging__models.yml` — append two new sources: raw.meda_bronze_records and science.meda_silver_readings; append model entries stg_meda_bronze (description: 'Validated MEDA Bronze records, quarantined excluded') and stg_meda_silver (description: 'Calibrated MEDA Silver readings per sampling instant')
- [ ] T020 [P] [US3] Update `dbt/models/marts/_marts__models.yml` — append fct_meda_sol_summary model entry with column-level tests: not_null on sol, temp_min_c, temp_max_c, temp_avg_c, pressure_avg_hpa, wind_speed_max_ms, uv_dose_wh_m2, reading_count, anomaly_count; unique on sol; accepted_range [−120,40] on temp_min_c/temp_max_c/temp_avg_c; accepted_range [0,120] on pressure_avg_hpa; accepted_range [0,100] on wind_speed_max_ms; accepted_range [0,240] on uv_dose_wh_m2; accepted_values >=0 on anomaly_count; expression_is_true: "temp_min_c <= temp_avg_c and temp_avg_c <= temp_max_c" (CE-004)
- [ ] T021 [US3] Implement `dbt_build` task in `airflow/dags/meda_pipeline.py` — use BashOperator or subprocess.run(['dbt','build','--select','fct_meda_sol_summary','--project-dir', os.getenv('DBT_PROJECT_DIR','/opt/airflow/dbt'),'--profiles-dir', os.getenv('DBT_PROFILES_DIR','/opt/airflow/dbt')], check=True, capture_output=True, text=True); log stdout/stderr; re-raise CalledProcessError as AirflowException so task fails and retries (CE-004)
- [ ] T022 [US3] Implement `commit_kafka_offsets` task in `airflow/dags/meda_pipeline.py` — pull consumer object from XCom key 'kafka_consumer'; call kafka_offsets.commit_kafka_offsets(consumer) only after dbt_build task has succeeded (deferred commit ensures at-least-once delivery with Silver+Postgres+Gold all confirmed, RF-009)
- [ ] T023 [US3] Implement `notify` task in `airflow/dags/meda_pipeline.py` — pull XCom keys: 'raw_messages' (batch_size), 'anomaly_count'; query COUNT(*) from raw.meda_bronze_records and science.meda_silver_readings for the processed sols; log summary: batch_size processed, bronze_upserted, silver_upserted, anomalies_detected, offsets_committed=True, pipeline='meda_full_pipeline'; return summary dict to XCom

**Checkpoint**: US3 complete — `dbt build` en verde, Gold JSON escrito, offsets commitados. Testeable con quickstart.md §Escenario 5.

---

## Phase 6: User Story 4 — Simulador MEDA determinista (Priority: P2)

**Goal**: El equipo de ingeniería puede generar telemetría MEDA sintética realista con patrón diurno de temperatura y publicarla en Kafka con semilla fija para reproducibilidad exacta en CI.

**Independent Test**: Ejecutar `meda_simulator.py --seed 42 --sols 1 --dry-run --output /tmp/run1.bin` dos veces; `sha256sum /tmp/run1.bin` debe producir hashes idénticos (quickstart.md §Escenario 6). Verificar mínimo de temperatura entre 02:00–06:00 LMST y máximo entre 13:00–15:00 LMST.

- [ ] T024 [US4] Create `simulator/meda_simulator.py` — argparse CLI: --seed INT required, --sols INT default=1 (validate range [1,999], raise ValueError('sols must be in [1, 999]') for invalid), --topic STR default='telemetry.meda.raw', --bootstrap STR default=os.getenv('KAFKA_BOOTSTRAP','kafka:9092'), --corrupt-crc INT default=0 (number of packets to flip CRC byte for testing Bronze quarantine), --dry-run store_true, --output PATH (write concatenated binary payloads for SHA-256 determinism check); seed Python random.seed(args.seed) and numpy if available; SENSOR_APID map {'ATS':0xC0,'PS':0xC1,'WS':0xC2,'UV':0xC3,'HS':0xC4}; SENSOR_TYPE_ID map {'ATS':1,'PS':2,'WS':3,'UV':4,'HS':5}; sinusoidal temperature model T(lmst_h)=−60.0+30.0×math.sin(2×math.pi×(lmst_h−14.0)/24.659 − math.pi/2) per research.md §5; generate N_SAMPLES_PER_SOL (default 24) uniformly-spaced LMST samples per sol; for each sample×sensor: generate DN values from physical value using inverse calibration + Gaussian noise (σ=2 DN); pack secondary header with struct.pack('>dIHH', sclk, sol, sensor_type_id, 0); build CCSDS primary header (APID, length); compute CRC-16/CCITT via ccsds_encoder.crc16_ccitt over packet-without-last-2-bytes; repack with CRC; if packet index in corrupt_set: flip last byte of CRC; assemble JSON message per kafka-topic-schema.md (packet_id=sha256[:16], payload_b64=base64.b64encode, crc_computed, produced_utc=datetime.utcnow().isoformat()+'Z', simulator_seed=args.seed); if not dry-run: publish via confluent_kafka.Producer.produce(topic, key=packet_id, value=json_bytes), flush(); if dry-run and --output: write concatenated raw CCSDS bytes to args.output for external SHA-256 comparison (RF-010)

**Checkpoint**: US4 complete — simulador determinista disponible. Habilita validación extremo a extremo CE-001 y CE-002 con quickstart.md §Escenario 1 y 6.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Entregables de portafolio y calidad de código que afectan todo el subsistema.

- [ ] T025 [P] Update `README.md` Mermaid architecture diagram — add MEDA subsystem as second data flow lane parallel to Mastcam-Z: meda_simulator.py → Kafka(telemetry.meda.raw) → meda_pipeline DAG [poll→ingest_raw→validate_bronze→calibrate_silver→detect_anomalies→build_gold_aggregates→dbt_build] → MinIO(meda-raw/silver/gold) + Postgres(meda_bronze_records/meda_silver_readings) → fct_meda_sol_summary; annotate calibration modules (meda_calibration.py, meda_anomaly_rules.py) per plan.md diagram (CE-007)
- [ ] T026 Run `ruff check` on all new files and fix any findings to reach zero-hallazgos state (CE-005): `ruff check airflow/plugins/meda_calibration.py airflow/plugins/meda_anomaly_rules.py airflow/dags/meda_pipeline.py simulator/meda_simulator.py tests/test_meda_calibration.py tests/test_meda_anomaly_rules.py`; fix each reported violation; confirm re-run returns exit code 0

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 and T002 start immediately in parallel
- **Foundational (Phase 2)**: Depends on Setup completion; T003–T006 all run in parallel
- **US1 Bronze (Phase 3)**: Depends on T001 (docker-compose buckets+topic), T002 (schema); T007 first, then T008–T010
- **US2 Silver (Phase 4)**: Depends on T003 (meda_calibration), T004 (meda_anomaly_rules), T002 (silver schema), and US1 (Bronze records exist); T011–T014 sequential
- **US3 Gold (Phase 5)**: Depends on US2 completion; T016/T017/T019/T020 parallel, T018 after T017, T021 after T018+T020, T022 after T021, T023 after T022
- **US4 Simulator (Phase 6)**: Depends on T001 (docker-compose Kafka topic declared); independent of US1–US3 in terms of code but enables their end-to-end validation
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Requires Phase 1+2 complete; no dependency on US2–US4
- **US2 (P1)**: Requires Phase 2 (T003, T004) + US1 complete
- **US3 (P2)**: Requires US2 complete
- **US4 (P2)**: Requires Phase 1 (docker-compose) complete; can be developed in parallel with US1–US3

### Within Each User Story

- DAG file (T007) must exist before any DAG task implementation
- calibrate_silver (T011) imports meda_calibration → T003 must be complete
- detect_anomalies (T014) imports meda_anomaly_rules → T004 must be complete
- fct_meda_sol_summary (T018) refs stg_meda_silver → T017 must be complete
- dbt_build task (T021) needs T018+T020 complete (model + tests yaml)
- commit_kafka_offsets (T022) must follow dbt_build (T021) for RF-009

### Parallel Opportunities

- T001 ‖ T002 (Phase 1 — different files)
- T003 ‖ T004 ‖ T005 ‖ T006 (Phase 2 — all different files)
- T008, T009, T010 within US1 depend on T007 but each implements a different function body
- T016 ‖ T017 ‖ T019 ‖ T020 (Phase 5 — different dbt files)
- T025 ‖ T026 can start in parallel (Polish)

---

## Parallel Example: Foundational Phase

```bash
# Launch all 4 foundational tasks simultaneously (different files, no deps):
Task A: "Create airflow/plugins/meda_calibration.py"
Task B: "Create airflow/plugins/meda_anomaly_rules.py"
Task C: "Write tests/test_meda_calibration.py"
Task D: "Write tests/test_meda_anomaly_rules.py"
```

## Parallel Example: User Story 3

```bash
# After T015 (build_gold_aggregates impl), launch dbt files together:
Task A: "Create dbt/models/staging/stg_meda_bronze.sql"
Task B: "Create dbt/models/staging/stg_meda_silver.sql"
Task C: "Update dbt/models/staging/_staging__models.yml"
Task D: "Update dbt/models/marts/_marts__models.yml"
# Then T018 (fct_meda_sol_summary.sql) after Task B
# Then T021 (dbt_build task) after T018 + Task D
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T006, all parallel)
3. Complete Phase 3: US1 Bronze (T007–T010)
4. **STOP and VALIDATE**: `pytest tests/test_meda_calibration.py tests/test_meda_anomaly_rules.py -v` all green; MinIO + Bronze rows verified via quickstart.md §Escenario 1–3
5. Complete Phase 4: US2 Silver (T011–T014)
6. **STOP and VALIDATE**: Silver rows in Postgres with calibrated values; quickstart.md §Escenario 4 passes
7. Deliver/demo Silver pipeline

### Incremental Delivery

1. Setup + Foundational → pure modules tested without Docker
2. US1 Bronze → Raw storage + Bronze catalog (partial pipeline)
3. US2 Silver → Full Bronze→Silver with calibration + anomaly detection
4. US3 Gold → dbt mart + JSON Gold (full analytical cycle, CE-001 satisfied)
5. US4 Simulator → deterministic synthetic data (enables CI reproducibility, CE-002)
6. Polish → ruff clean, README updated (CE-005, CE-007)

### Parallel Team Strategy

With multiple developers after Phase 2 complete:
- Developer A: US1 (Bronze) → US2 (Silver) sequentially
- Developer B: US4 (Simulator) in parallel — no code dependency on A
- Developer C: US3 dbt models (T016–T020) after Silver schema is confirmed from T013

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps each task to its user story for traceability
- Test tasks (T005, T006) are required: CE-003 mandates 100% calibration coverage
- Verify `pytest` and `ruff check` actually run green before marking tasks complete (Constitución IV)
- All thresholds and credentials via os.getenv() — no hardcoding (Constitución III, V)
- meda_calibration.py and meda_anomaly_rules.py must have zero Airflow/Kafka/Postgres imports (Constitución III — responsabilidad única)
- Raw objects in MinIO are immutable: guard with stat_object before PUT (Constitución II)
- Upsert ON CONFLICT in all Postgres writes (Constitución III — idempotencia)
- Kafka offsets committed only after Gold+dbt success (RF-009, commit_kafka_offsets pattern)
- Do NOT modify anomaly_rules.py or calibration.py (existing Mastcam-Z modules) — RF-007
