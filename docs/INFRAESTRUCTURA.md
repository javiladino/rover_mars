# Infraestructura — cómo está conectada y sus dependencias

> Generado a partir de `docker-compose.yml`, `airflow/dags/*.py`, `database/*.sql`,
> `dbt/models/**`, `dbt/models/staging/_staging__sources.yml` y
> `specs/001-meda-pipeline/quickstart.md`. Fecha: 2026-09-30.
> Versión interactiva (con leyenda de color y tablas): [artefacto publicado](https://claude.ai/artifact/TV5tCL6dEiovzc6Q2xuVfG).

Dos pipelines de telemetría (**Mastcam-Z** y **MEDA**) comparten el mismo stack
de contenedores: 13 servicios Docker, 7 tópicos Kafka, 9 buckets MinIO/S3,
3 schemas Postgres y 8 modelos dbt.

---

## 1. Topología de infraestructura

Todo vive en la red Docker `rover_net`. Las flechas sólidas son dependencias de
datos reales (quién escribe/lee qué); las punteadas son acceso de solo lectura
ad-hoc que no bloquea el arranque de nada.

```mermaid
flowchart TB
    subgraph PROD["Productores"]
        SIM["rover_simulator<br/>mastcamz_simulator.py<br/>(contenedor, always-on)"]
        MEDASIM["meda_simulator.py<br/>(CLI manual vía<br/>docker compose exec)"]
        DSN["dsn_receiver<br/>(contenedor)"]
    end

    subgraph MSG["Kafka + Zookeeper"]
        KAFKA["kafka<br/>mastcamz.raw.images<br/>mastcamz.telemetry<br/>mastcamz.ccsds.packets<br/>dsn.ground.received<br/>etl.bronze.ready · etl.silver.ready<br/>telemetry.meda.raw"]
        ZK["zookeeper"]
        KUI["kafka_ui :8085"]
        ZK --- KAFKA
        KUI -.observa.-> KAFKA
    end

    subgraph ORCH["Airflow — LocalExecutor"]
        ASCHED["airflow_scheduler"]
        AWEB["airflow_webserver :8080"]
        DAG1["DAG mastcamz_full_pipeline<br/>10 tareas"]
        DAG2["DAG meda_full_pipeline<br/>11 tareas"]
        DBT["dbt build<br/>(BashOperator, ambos DAGs)"]
        ASCHED --> DAG1
        ASCHED --> DAG2
        AWEB -.UI trigger.-> ASCHED
    end

    subgraph STORE["Almacenamiento"]
        MINIO["minio<br/>mastcamz-raw/bronze/silver/gold/pds4<br/>meda-raw/bronze/silver/gold"]
        PG["postgres 16 + PostGIS<br/>public · raw · science"]
    end

    subgraph VIZ["Consumo"]
        GRAF["grafana :3001"]
        JUP["jupyter :8888"]
    end

    SIM -- produce --> KAFKA
    MEDASIM -- produce --> KAFKA
    DSN -- consume --> KAFKA
    DSN -- produce etl.bronze.ready --> KAFKA
    DSN -- Bronze JSON --> MINIO

    KAFKA -- etl.bronze.ready --> DAG1
    KAFKA -- telemetry.meda.raw --> DAG2

    DAG1 <--> MINIO
    DAG1 <--> PG
    DAG2 <--> MINIO
    DAG2 <--> PG
    DAG1 --> DBT
    DAG2 --> DBT
    DBT <--> PG

    PG --> GRAF
    MINIO -.ad-hoc.-> JUP
    PG -.ad-hoc.-> JUP

    classDef mastcamz fill:#2a1d12,stroke:#e2762f,color:#f5d9bd
    classDef meda fill:#0f2624,stroke:#38b6a6,color:#c3ede8
    classDef shared fill:#181c2c,stroke:#6c86d1,color:#d6dcf7

    class SIM,DSN,DAG1 mastcamz
    class MEDASIM,DAG2 meda
    class KAFKA,ZK,KUI,ASCHED,AWEB,DBT,MINIO,PG,GRAF,JUP shared
```

**Nota:** `rover_simulator` corre siempre encendido y genera datos Mastcam-Z;
`meda_simulator.py` vive en el mismo contenedor pero se ejecuta manualmente con
`docker compose exec rover_simulator python meda_simulator.py ...` — no tiene
schedule propio (ver `specs/001-meda-pipeline/quickstart.md`).

---

## 2. Grafo de tareas de cada DAG

Ambos DAG siguen el mismo patrón (Fase 7 de
`docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`): el commit de offsets de Kafka
se difiere hasta el final, después de que Gold y dbt confirman éxito — así un
fallo a mitad de camino no pierde mensajes, porque el reproceso es idempotente.

### `mastcamz_full_pipeline` (cron `*/15 * * * *`)

```mermaid
flowchart TB
    A1["poll_bronze_queue"] --> A2["validate_raw_products"]
    A2 --> A3["radiometric_calibration"]
    A3 --> A4["geometric_calibration"]
    A4 --> A5["write_silver_layer"]
    A5 --> A6["update_postgis"]
    A5 --> A7["anomaly_detection"]
    A6 --> A8["build_gold_aggregates"]
    A7 --> A8
    A6 --> A9["dbt_build"]
    A8 --> A10["commit_kafka_offsets"]
    A9 --> A10
    A10 --> A11["notify_science_team"]

    classDef mastcamz fill:#2a1d12,stroke:#e2762f,color:#f5d9bd
    class A1,A2,A3,A4,A5,A6,A7,A8,A9,A10,A11 mastcamz
```

### `meda_full_pipeline` (manual, `schedule_interval=None`)

```mermaid
flowchart TB
    B1["poll_meda_queue"] --> B2["ingest_raw"]
    B2 --> B3["validate_bronze"]
    B3 --> B4["calibrate_silver"]
    B4 --> B5["write_silver_minio"]
    B5 --> B6["update_silver_postgres"]
    B6 --> B7["detect_anomalies"]
    B7 --> B8["build_gold_aggregates"]
    B8 --> B9["dbt_build"]
    B9 --> B10["commit_kafka_offsets"]
    B10 --> B11["notify"]

    classDef meda fill:#0f2624,stroke:#38b6a6,color:#c3ede8
    class B1,B2,B3,B4,B5,B6,B7,B8,B9,B10,B11 meda
```

| DAG | Trigger | Tabla Bronze | Tabla Silver | Quarantine |
|---|---|---|---|---|
| `mastcamz_full_pipeline` | cron `*/15 * * * *` | — (Bronze vive en MinIO, no en Postgres) | `public.image_products` | No aplica |
| `meda_full_pipeline` | manual (`schedule_interval=None`) | `raw.meda_bronze_records` | `science.meda_silver_readings` | `quarantine_reason`: `crc_mismatch` · `unknown_apid` · `payload_too_large` · `missing_fields` |

---

## 3. Linaje de modelos dbt

Cuatro fuentes, cuatro modelos de staging, un seed estático y cuatro marts.
`stg_meda_bronze` existe y pasa sus tests, pero hoy ningún mart lo referencia
todavía — es una hoja suelta en el grafo, no un error.

```mermaid
flowchart LR
    SRC1[("source: public.image_products")]
    SRC2[("source: public.telemetry_records")]
    SRC3[("source: raw.meda_bronze_records")]
    SRC4[("source: science.meda_silver_readings")]
    SEED[("seed: dsn_stations.csv")]

    STG1["stg_image_products"]
    STG2["stg_telemetry_records"]
    STG3["stg_meda_bronze"]
    STG4["stg_meda_silver"]

    MART1["dim_dsn_stations"]
    MART2["fct_sol_filter_coverage"]
    MART3["fct_sol_summary"]
    MART4["fct_meda_sol_summary"]

    SRC1 --> STG1
    SRC2 --> STG2
    SRC3 --> STG3
    SRC4 --> STG4

    STG1 --> MART1
    SEED --> MART1
    STG1 --> MART2
    STG1 --> MART3
    STG2 --> MART3
    STG4 --> MART4

    classDef mastcamz fill:#2a1d12,stroke:#e2762f,color:#f5d9bd
    classDef meda fill:#0f2624,stroke:#38b6a6,color:#c3ede8
    classDef shared fill:#181c2c,stroke:#6c86d1,color:#d6dcf7

    class SRC1,SRC2,STG1,STG2,MART1,MART2,MART3 mastcamz
    class SRC3,SRC4,STG3,STG4,MART4 meda
    class SEED shared
```

---

## Hallazgo corregido

`specs/001-meda-pipeline/quickstart.md` usaba nombres de servicio que no
existían en `docker-compose.yml` (`simulator` en vez de `rover_simulator`,
`airflow-scheduler`/`airflow-worker` en vez de `airflow_scheduler`, y un
comando `mc` ejecutado dentro del contenedor `minio`, que solo trae el
servidor, no el cliente). Ya se corrigió directamente en ese archivo.
