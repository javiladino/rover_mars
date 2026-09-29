# Implementation Plan: Pipeline de Telemetría MEDA

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-meda-pipeline/spec.md`

## Summary

Implementar un segundo subsistema de datos en la arquitectura Medallion del rover Mars usando el instrumento MEDA (Mars Environmental Dynamics Analyzer) como fuente. El pipeline replica el patrón establecido por Mastcam-Z — simulador CCSDS determinista → Kafka → DAG Airflow 10 tareas → Raw/Bronze/Silver/Gold — con nuevos módulos de calibración física (°C, hPa, m/s, W/m², %) basados en Sebastián et al. 2021, reglas de anomalía MEDA en módulo independiente, y modelo dbt `fct_meda_sol_summary` que agrega lecturas ambientales por sol marciano.

## Technical Context

**Language/Version**: Python 3.11 (`python:3.11-slim`, `apache/airflow:2.9.1-python3.11` — stack fijo por Constitución)

**Primary Dependencies**: Apache Airflow 2.9 (LocalExecutor), confluent-kafka 7.6, psycopg2-binary, minio, dbt-core/dbt-postgres 1.8.x, pytest, ruff — sin dependencias nuevas respecto al pipeline Mastcam-Z

**Storage**: PostgreSQL 16 + PostGIS 3.4 (tablas `meda_bronze_records` y `meda_silver_readings` nuevas), MinIO (buckets `meda-raw`, `meda-bronze`, `meda-silver`, `meda-gold` — sin nuevo servicio)

**Testing**: pytest, Python 3.11, sin infraestructura real para los módulos puros (`meda_calibration.py`, `meda_anomaly_rules.py`)

**Target Platform**: Linux Docker containers — mismo entorno que Mastcam-Z (`docker-compose.yml`, `LocalExecutor`)

**Project Type**: Data pipeline ETL — extensión de subsistema existente

**Performance Goals**: 100 lecturas MEDA extremo a extremo en < 5 minutos con `docker compose up` (CE-001)

**Constraints**: LocalExecutor Airflow; docker-compose local; contexto Docker = raíz del repo; sin nuevo servicio gestionado AWS; sin modificar `anomaly_rules.py` ni `calibration.py` existentes

**Scale/Scope**: Lotes de ~100 paquetes CCSDS por run; 5 tipos de sensor × N instantes de muestreo por sol

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Estado | Evidencia / Plan |
|-----------|--------|------------------|
| I. Fidelidad de dominio | ✓ PASS | Calibración MEDA citando Sebastián et al. 2021 (JGR Planets, 126, e2021JE006823); APIDs 0x0C0–0x0CF según tabla APID del proyecto; rangos operativos tomados del ICD de MEDA; simplificaciones declaradas explícitamente en `meda_calibration.py` |
| II. Medallion contract | ✓ PASS | Raw inmutable (`meda-raw/{sol}/{apid}/{packet_id}.bin`); Bronze solo valida CRC + APID + tamaño + campos obligatorios; Silver calibra DN→SI y consolida por `(sol, sclk)`; Gold (`fct_meda_sol_summary`) agrega por sol vía dbt |
| III. Determinismo / idempotencia / parametrización / responsabilidad única | ✓ PASS | Claves MinIO deterministas por `(sol, apid, packet_id)` — sin timestamp variable; upsert `ON CONFLICT DO UPDATE` en Bronze y Silver; Kafka commit diferido hasta confirmar éxito en Silver + Postgres + dbt (patrón `commit_kafka_offsets`); calibración pura en `meda_calibration.py` sin I/O; anomalías en `meda_anomaly_rules.py` sin tocar `anomaly_rules.py` (aislamiento tests Mastcam-Z — RF-007) |
| IV. Verificación real | ✓ PASS | `tests/test_meda_calibration.py` con 100% cobertura de funciones de calibración (CE-003); `tests/test_meda_anomaly_rules.py`; `ruff check` sobre todos los archivos nuevos (CE-005); criterio de aceptación = corrida en verde, no revisión del diff |
| V. Seguridad de secretos | ✓ PASS | Todos los parámetros vía `os.getenv()` con defaults razonables; sin credenciales hardcodeadas en código ni en `docker-compose.yml` |
| VI. Costo consciente | ✓ PASS | Sin nuevo servicio gestionado AWS; reutiliza MinIO, Postgres, Kafka y Airflow existentes |
| VII. ADR para decisiones no triviales | ✓ PASS | MEDA reutiliza la arquitectura Mastcam-Z sin divergencia técnica — no se requiere ADR nuevo; la coexistencia `build_gold_aggregates` + dbt ya está cubierta por ADR-001 |
| VIII. dbt para transformación Gold | ✓ PASS | `fct_meda_sol_summary` implementado como modelo dbt con tests declarativos (`not_null`, `unique`, rangos físicos); `build_gold_aggregates` en el DAG escribe JSON Gold para Grafana/dashboard (coexistencia deliberada documentada por ADR-001) |

**Resultado del GATE**: PASS. Ninguna violación sin justificar.

### Re-check post-diseño (Phase 1)

Ver [research.md — sección APID](research.md#1-apid-mapping-meda): discrepancia resuelta — el simulador MEDA usará el rango 0x0C0–0x0CF propio, sin modificar el `ccsds_encoder.py` existente (que conserva 0x01A7 como placeholder de desarrollo). GATE mantiene PASS.

## Project Structure

### Documentation (this feature)

```text
specs/001-meda-pipeline/
├── plan.md              # Este archivo
├── research.md          # Phase 0 — decisiones técnicas y calibración
├── data-model.md        # Phase 1 — entidades, campos, relaciones
├── quickstart.md        # Phase 1 — guía de validación extremo a extremo
├── contracts/
│   ├── kafka-topic-schema.md            # Phase 1 — schema Kafka topic
│   └── ccsds-secondary-header-meda.md  # Phase 1 — formato header CCSDS MEDA
└── tasks.md             # Phase 2 — generado por /speckit-tasks (NO por /speckit-plan)
```

### Source Code (repository root)

```text
simulator/
├── meda_simulator.py          # nuevo — simulador MEDA, --seed, --sols, patrón diurno
└── ccsds_encoder.py           # existente — reutilizado sin modificación

airflow/
├── dags/
│   └── meda_pipeline.py       # nuevo — DAG 10 tareas, patrón Mastcam-Z
└── plugins/
    ├── meda_calibration.py    # nuevo — funciones puras calibración MEDA (sin I/O)
    ├── meda_anomaly_rules.py  # nuevo — módulo independiente reglas anomalía MEDA
    ├── calibration.py         # existente — sin modificación
    ├── anomaly_rules.py       # existente — sin modificación (RF-007)
    └── kafka_offsets.py       # existente — reutilizado sin modificación

database/
└── meda_schema.sql            # nuevo — tablas Bronze y Silver MEDA

dbt/models/
├── staging/
│   ├── stg_meda_bronze.sql    # nuevo — staging Bronze MEDA
│   └── _staging__models.yml   # existente — ampliar con fuente MEDA
└── marts/
    ├── fct_meda_sol_summary.sql   # nuevo — Gold por sol
    └── _marts__models.yml         # existente — ampliar con MEDA

tests/
├── test_meda_calibration.py       # nuevo — cobertura 100% calibración
└── test_meda_anomaly_rules.py     # nuevo — cobertura reglas anomalía

docker-compose.yml    # existente — agregar buckets meda-* y topic telemetry.meda.raw
README.md             # existente — actualizar diagrama Mermaid con subsistema MEDA
```

**Structure Decision**: Extensión del proyecto único existente (Option 1). Todos los archivos nuevos siguen las convenciones de nomenclatura y ubicación establecidas por Mastcam-Z. No se crea ninguna carpeta raíz nueva ni servicio nuevo.

## Complexity Tracking

> No hay violaciones de Constitución que justificar.
