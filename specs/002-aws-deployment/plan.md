# Implementation Plan: Despliegue Híbrido en AWS con Datos Reales de Mastcam-Z

**Branch**: `002-aws-deployment` | **Date**: 2026-10-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-aws-deployment/spec.md`

## Summary

Cerrar los tres escenarios P1/P2 que quedaron abiertos tras el primer
despliegue real en AWS (ya ejecutado en esta sesión: Terraform aplicado,
Airflow accesible por túnel SSH, `dbt build` en verde contra RDS):
(1) el cliente de almacenamiento debe usar el rol IAM del EC2 en vez de
claves estáticas vacías, que hoy producen `AccessDenied` en
`build_gold_aggregates`; (2) la capa Raw debe poder recibir productos reales
de Mastcam-Z del bundle público `mastcamz_ops_raw` del archivo PDS, marcados
como tales, dejando el simulador acotado al tramo CCSDS/DSN; (3) un job
PySpark en AWS Glue debe reproducir `science.sol_filter_coverage` sobre el
mismo origen que la vista SQL (RDS vía JDBC) y compararse contra ella, para
decidir con datos si Spark se justifica en este volumen. El enfoque técnico
de cada punto está resuelto en `research.md`.

## Technical Context

**Language/Version**: Python 3.11 (igual al resto del proyecto — `common/`,
`airflow/`, `simulator/`, `ingestion/`)

**Primary Dependencies**: `minio>=7.2.7` (ya pinneado; se usa su
`credentials.IamAwsProvider`, sin agregar `boto3`), `requests` (ya presente
en `simulator/requirements.txt`, se reutiliza para el downloader PDS4),
AWS Glue 4.0 (runtime PySpark gestionado, no se instala localmente)

**Storage**: PostgreSQL 16 en RDS (ya desplegado, `rover_mars` db, PostGIS
activo), S3 (buckets `raw`/`bronze`/`silver`/`gold` ya creados vía
Terraform)

**Testing**: `pytest` + `ruff check`, Python 3.11 — mismo runtime real que
`python:3.11-slim` y `apache/airflow:2.9.1-python3.11` (Principio IV)

**Target Platform**: EC2 `t3.small` (Airflow, ya desplegado) + AWS Glue
(job PySpark, nuevo)

**Project Type**: Extensión de un pipeline de datos existente (no aplica
mobile/web)

**Performance Goals**: No aplica un objetivo de throughput — el volumen es
deliberadamente acotado (1-2 sols reales) para mantenerse dentro del
crédito de estudiante (Principio VI)

**Constraints**: Sin NAT Gateway; EC2 con memoria limitada (ya documentado
en esta sesión: `t3.small` con swap en uso bajo carga); ningún secreto
estático nuevo (Principio V); `terraform apply` siempre precedido de
revisión de `plan` (ya establecido en `infra/aws/README.md`)

**Scale/Scope**: Subconjunto acotado del archivo PDS4 real (1-2 sols, del
orden de 10-20 productos según el manifiesto `collection_data_inventory.csv`);
el job de Glue opera sobre ese mismo subconjunto

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — sin cambios, ningún hallazgo de diseño contradice lo evaluado antes de investigar.*

| Principio | Evaluación |
|---|---|
| I. Fidelidad de dominio | Cumple. Fuente real verificada contra el archivo público PDS (no simulada); el formato de producto real se documenta tal cual es, sin inventar uno nuevo. El hallazgo de que el README actual no marca su formato como simplificación queda registrado como deuda, no se oculta. |
| II. Contrato Medallion | Cumple. Se eligió `ops_raw` (sin calibrar) precisamente para no romper el contrato: Silver sigue siendo donde ocurre la calibración, ahora también sobre datos reales. |
| III. Determinismo, idempotencia, parametrización, SRP | Cumple. La ingesta re-ejecutada no duplica (FR-007); `build_object_store_client` sigue con responsabilidad única (fábrica de cliente, nada de lógica de negocio); nombres de bucket/credenciales siguen parametrizados por entorno. |
| IV. Verificación real | Cumple, ver `quickstart.md` — comandos `pytest`/`ruff` explícitos para el cambio de `storage.py`, y criterio de aceptación verificable (sin `AccessDenied`, filas idénticas Glue vs SQL) para los otros dos escenarios. |
| V. Seguridad de secretos | Cumple. `IamAwsProvider` elimina la necesidad de claves S3 estáticas; la conexión JDBC de Glue a RDS usa el mismo patrón de credenciales ya en SSM, no credenciales nuevas en texto plano. |
| VI. Ingeniería consciente del costo | Cumple. Glue Job en vez de EMR (research.md, Decisión 3); subconjunto acotado de datos reales; `quickstart.md` ordena los pasos para minimizar el tiempo con EC2/RDS encendidos. |
| VII. ADR para decisión no trivial | Pendiente de redactar, no de decidir — las tres decisiones de `research.md` quedan pendientes de pasar a `docs/ANALISIS_MODERN_DATA_STACK.md` como ADR-021, ADR-022 y ADR-023 durante la implementación (Principio VII pide el ADR junto con o antes de implementar, no junto con el plan). |
| VIII. Transformación declarativa y CI | No aplica cambio a dbt en esta feature — el job de Glue no reemplaza ni duplica un modelo dbt, es una comparación puntual (Escenario 3). CI (`lint.yml`, `test.yml`, `dbt-ci.yml`, `docker-build.yml`) debe seguir en verde con el cambio de `storage.py`. |

Sin violaciones — no se completa la sección de Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-aws-deployment/
├── spec.md              # Ya existente
├── plan.md              # Este archivo
├── research.md          # Fase 0 — 3 decisiones técnicas
├── data-model.md         # Fase 1 — columna origen + entidades
├── quickstart.md         # Fase 1 — guía de validación, marca qué pasos requieren EC2/RDS encendidos
├── contracts/
│   └── cobertura_sol_schema.md
└── tasks.md              # Pendiente — lo genera /speckit-tasks
```

### Source Code (repository root)

```text
common/rovermars_common/
└── storage.py                 # Modificar: IamAwsProvider cuando secure=True sin claves

tests/
└── test_storage.py            # Agregar: test del camino IamAwsProvider (mockeado, sin red real)

ingestion/
└── pds4_real_ingest.py        # Nuevo: script de descarga acotada del bundle ops_raw,
                                # valida checksum, sube a raw/, inserta en image_products

database/
└── schema.sql                 # Modificar: ALTER TABLE image_products ADD COLUMN origen (idempotente)

infra/aws/
├── glue_athena.tf             # Modificar o nuevo archivo glue_job.tf: aws_glue_connection,
│                               # aws_glue_job, regla de ingreso en aws_security_group.rds
└── glue/
    └── sol_filter_coverage_job.py   # Nuevo: script PySpark del job de Glue

docs/
└── ANALISIS_MODERN_DATA_STACK.md   # Agregar ADR-021 (IamAwsProvider), ADR-022 (fuente real
                                      # ops_raw), ADR-023 (Glue vs EMR/local) — durante implementación
```

**Structure Decision**: Extensión directa de los directorios ya existentes
del proyecto (`common/`, `tests/`, `ingestion/`, `database/`, `infra/aws/`,
`docs/`) — no se introduce una estructura de proyecto nueva. `ingestion/`
ya es el lugar natural para scripts de ingesta (contiene `dsn_receiver.py`);
`infra/aws/glue/` es nuevo porque hoy no existe ningún script PySpark en el
repo, igual que `infra/aws/lambda/` ya aloja el código de la Lambda
existente.

## Complexity Tracking

*Sin violaciones de la Constitution Check — sección no aplica.*
