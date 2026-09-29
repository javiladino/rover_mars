# Quickstart — Validación del Pipeline MEDA

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29

Esta guía documenta cómo validar que el pipeline MEDA funciona extremo a extremo. No es un manual de implementación — los detalles de código están en `tasks.md`.

---

## Prerequisitos

1. **Docker Desktop** corriendo con al menos 4 GB de RAM asignados.
2. `docker compose up` completo y todos los servicios healthy (Kafka, MinIO, Postgres, Airflow).
3. Rama `001-meda-pipeline` con la implementación completa.
4. `pyproject.toml` / Python 3.11 disponible para correr los tests unitarios localmente.

```bash
# Verificar que los servicios están healthy
docker compose ps

# Salida esperada: todos en estado "healthy" o "running"
```

---

## Escenario 1 — Ingestión y validación Bronze (P1)

**Criterio de aceptación**: Paquetes CCSDS MEDA fluyen de Kafka a MinIO Raw y Postgres Bronze con CRC válido. Ver [spec.md § Escenario 1](spec.md#escenario-1).

### Paso 1 — Iniciar el simulador MEDA

```bash
docker compose exec simulator python meda_simulator.py \
  --seed 42 \
  --sols 1 \
  --topic telemetry.meda.raw \
  --bootstrap kafka:9092
```

**Output esperado**: 5 líneas de confirmación (una por tipo de sensor × N instantes del sol 0).

### Paso 2 — Activar el DAG en Airflow

Abrir Airflow UI en `http://localhost:8080` → DAG `meda_full_pipeline` → "Trigger DAG".

Alternativamente:

```bash
docker compose exec airflow-scheduler \
  airflow dags trigger meda_full_pipeline
```

### Paso 3 — Verificar Raw en MinIO

Abrir MinIO Console en `http://localhost:9001` → bucket `meda-raw` → verificar que existen objetos con estructura `{sol:04d}/{apid_hex}/{packet_id}.bin`.

O vía CLI:

```bash
docker compose exec minio \
  mc ls local/meda-raw/ --recursive | head -20
```

**Output esperado**: Al menos 5 objetos (uno por tipo de sensor), todos con tamaño > 0.

### Paso 4 — Verificar Bronze en Postgres

```bash
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT sensor_type, crc_valid, schema_valid, quarantine_reason, COUNT(*)
   FROM raw.meda_bronze_records
   GROUP BY 1,2,3,4 ORDER BY 1;"
```

**Output esperado**:
```
 sensor_type | crc_valid | schema_valid | quarantine_reason | count
-------------+-----------+--------------+-------------------+-------
 ATS         | t         | t            |                   |    N
 HS          | t         | t            |                   |    N
 PS          | t         | t            |                   |    N
 UV          | t         | t            |                   |    N
 WS          | t         | t            |                   |    N
```

Zero filas con `quarantine_reason IS NOT NULL` en este escenario.

---

## Escenario 2 — Paquete con CRC corrupto (P1)

**Criterio de aceptación**: Paquete corrupto persiste en Bronze con `crc_valid = false` y no llega a Silver. Ver [spec.md § Escenario 1, caso 2](spec.md#escenario-1).

```bash
# El simulador acepta --corrupt-crc para generar un paquete deliberadamente corrupto
docker compose exec simulator python meda_simulator.py \
  --seed 99 --sols 1 --corrupt-crc 1 \
  --topic telemetry.meda.raw \
  --bootstrap kafka:9092

# Después de que el DAG procese:
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT packet_id, crc_valid, quarantine_reason
   FROM raw.meda_bronze_records
   WHERE crc_valid = false LIMIT 5;"
```

**Output esperado**: Al menos 1 fila con `crc_valid = false` y `quarantine_reason = 'crc_mismatch'`.

```bash
# Verificar que no llegó a Silver:
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT COUNT(*) FROM science.meda_silver_readings WHERE sol = 0;"
```

**Output esperado**: 0 filas para el sol del paquete corrupto (si todos los paquetes de ese sol estaban corruptos) o exclusión del instante afectado.

---

## Escenario 3 — Idempotencia (P1)

**Criterio de aceptación**: Re-ejecutar el mismo lote produce exactamente el mismo estado final. Ver [spec.md § Escenario 1, caso 3](spec.md#escenario-1) y [Escenario 2, caso 3](spec.md#escenario-2).

```bash
# Capturar estado antes del segundo run
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT COUNT(*) as bronze_count FROM raw.meda_bronze_records;" > state_before.txt
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT COUNT(*) as silver_count FROM science.meda_silver_readings;" >> state_before.txt

# Re-enviar los mismos datos (misma semilla)
docker compose exec simulator python meda_simulator.py \
  --seed 42 --sols 1 \
  --topic telemetry.meda.raw --bootstrap kafka:9092

# Trigger del DAG nuevamente
docker compose exec airflow-scheduler \
  airflow dags trigger meda_full_pipeline

# Capturar estado después
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT COUNT(*) as bronze_count FROM raw.meda_bronze_records;" > state_after.txt
```

**Output esperado**: `state_before.txt` == `state_after.txt` (mismos conteos, sin duplicados).

---

## Escenario 4 — Calibración Silver (P1)

**Criterio de aceptación**: ATS calibra correctamente; presión fuera de rango genera `anomaly_flag = true`.

```bash
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT sol, sclk,
          temperature_ats_c, pressure_hpa,
          wind_speed_ms, uv_irradiance_w_m2, humidity_pct,
          anomaly_flag, anomaly_reason
   FROM science.meda_silver_readings
   ORDER BY sol, sclk
   LIMIT 10;"
```

**Output esperado**:
- `temperature_ats_c` en rango [−120, +40] para todas las filas sin anomalía.
- Si hay lecturas con anomalía: `anomaly_flag = true` y `anomaly_reason` con texto descriptivo.
- `pressure_hpa` en rango [0, 120]; filas fuera de rango tienen `anomaly_reason = 'pressure_out_of_range'`.

---

## Escenario 5 — dbt Gold (P2)

**Criterio de aceptación**: `fct_meda_sol_summary` tiene una fila por sol con campos no nulos y tests en verde.

```bash
# Ejecutar dbt build contra los datos Silver ya existentes
docker compose exec airflow-worker bash -c \
  "cd /opt/airflow/dbt && dbt build --select fct_meda_sol_summary"
```

**Output esperado**: `Completed successfully` con todos los tests en verde.

```bash
# Verificar resultado:
docker compose exec postgres psql -U rover -d rover_mars -c \
  "SELECT sol, temp_min_c, temp_max_c, temp_avg_c,
          pressure_avg_hpa, wind_speed_max_ms, uv_dose_wh_m2,
          reading_count, anomaly_count
   FROM marts.fct_meda_sol_summary
   ORDER BY sol;"
```

---

## Escenario 6 — Simulador Determinista (P2)

**Criterio de aceptación**: Dos ejecuciones con la misma semilla producen payloads idénticos.

```bash
# Run 1
docker compose exec simulator python meda_simulator.py \
  --seed 42 --sols 1 --dry-run --output /tmp/run1.bin

# Run 2
docker compose exec simulator python meda_simulator.py \
  --seed 42 --sols 1 --dry-run --output /tmp/run2.bin

# Comparar
docker compose exec simulator sha256sum /tmp/run1.bin /tmp/run2.bin
```

**Output esperado**: Los dos hashes SHA-256 son idénticos.

---

## Tests Unitarios (sin infraestructura)

```bash
# Desde la raíz del repo, Python 3.11
pytest tests/test_meda_calibration.py tests/test_meda_anomaly_rules.py -v

# Lint
ruff check airflow/plugins/meda_calibration.py \
           airflow/plugins/meda_anomaly_rules.py \
           airflow/dags/meda_pipeline.py \
           simulator/meda_simulator.py
```

**Output esperado**: todos los tests en verde; `ruff` sin hallazgos.

---

## Criterios de Éxito Cross-check

| Criterio | Comando de verificación | Resultado esperado |
|----------|------------------------|--------------------|
| CE-001: < 5 min extremo a extremo | Medir tiempo entre `docker... trigger` y `end_pipeline` en Airflow | < 300 segundos |
| CE-002: Idempotencia | Ver Escenario 3 | Mismos conteos antes/después |
| CE-003: 100% cobertura calibración | `pytest --cov=airflow/plugins/meda_calibration.py` | Coverage = 100% |
| CE-004: dbt en verde | Ver Escenario 5 | `dbt build` sin errores |
| CE-005: ruff clean | `ruff check` comando arriba | 0 hallazgos |
| CE-006: CI verde | Push a rama y revisar `.github/workflows/` | Todos los checks en verde |
| CE-007: README actualizado | Revisar `README.md` diagrama Mermaid | Subsistema MEDA visible |
