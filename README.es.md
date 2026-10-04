[🇬🇧 English](README.md) · [🇫🇷 Français](README.fr.md) · 🇪🇸 **Español**

---

# Mars Rover — Mastcam-Z Data Engineering Simulation

[![Lint](https://img.shields.io/badge/lint-ruff-informational)](.github/workflows/lint.yml)
[![Tests](https://img.shields.io/badge/tests-pytest-informational)](.github/workflows/test.yml)
[![dbt](https://img.shields.io/badge/transform-dbt--core-orange)](dbt/)
[![IaC](https://img.shields.io/badge/cloud-Terraform%20%2B%20AWS-informational)](infra/aws/)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**Simulation of the complete NASA Mars 2020 / Perseverance Mastcam-Z data pipeline**, from image capture on the Martian surface to calibrated science products on Earth — implementado como un proyecto de **Modern Data Stack**: streaming (Kafka), arquitectura Medallion, orquestación (Airflow), transformación declarativa (dbt), calidad de datos, CI/CD e integración con AWS.

> This project replicates the exact data flow and methodology used by NASA's Jet Propulsion Laboratory (JPL) and the Multi-mission Image Processing Laboratory (MIPL) to process images from the Mastcam-Z stereo cameras aboard the Perseverance rover at Jezero Crater, Mars.

📄 **Documentación de arquitectura:** [docs/ANALISIS_MODERN_DATA_STACK.md](docs/ANALISIS_MODERN_DATA_STACK.md) (ADRs) · [docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md](docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md) (guía paso a paso, Fases 1-6)

---

## Architecture Overview

```mermaid
flowchart LR
    subgraph MARS["🔴 Mars — Jezero Crater"]
        CAM["📷 Mastcam-Z<br/>1648×1214 CCD, 16 filtros"]
        FPGA["⚡ CCSDS 133.0-B-2<br/>APID 0x01A5/0x01A6"]
        MEDA_INST["🌡️ MEDA<br/>ATS/PS/WS/UV/HS"]
        MEDA_FPGA["⚡ CCSDS 133.0-B-2<br/>APID 0x0C0–0x0C4"]
        CAM --> FPGA
        MEDA_INST --> MEDA_FPGA
    end
    subgraph RELAY["🚀 Relay"]
        MRO["🛸 MRO — UHF"]
        DSN["📡 DSN — X-Band<br/>Goldstone/Madrid/Canberra"]
        MRO --> DSN
    end
    subgraph GROUND["🏭 JPL / MIPL"]
        EDR["EDR → RDR → PDS4"]
    end
    subgraph SIM["💻 Stack de simulación (este repo)"]
        subgraph KAFKA_LAYER["Kafka"]
            KAFKA_MCZ["etl.bronze.ready<br/>(Mastcam-Z)"]
            KAFKA_MEDA["telemetry.meda.raw<br/>(MEDA)"]
        end
        subgraph MCZ_PIPE["Pipeline Mastcam-Z"]
            MCZ_DAG["Airflow: mastcamz_pipeline<br/>poll→validate→calibrate→silver→gold"]
            MCZ_CALIB["calibration.py<br/>anomaly_rules.py"]
        end
        subgraph MEDA_PIPE["Pipeline MEDA"]
            MEDA_DAG["Airflow: meda_pipeline<br/>poll→ingest→bronze→silver→gold"]
            MEDA_CALIB["meda_calibration.py<br/>meda_anomaly_rules.py"]
        end
        DBT["dbt<br/>fct_sol_summary<br/>fct_meda_sol_summary"]
        LAKE["MinIO / S3<br/>mastcamz-* / meda-*<br/>Raw→Bronze→Silver→Gold"]
        PG["PostGIS<br/>image_products<br/>meda_bronze_records<br/>meda_silver_readings"]
        KAFKA_MCZ --> MCZ_DAG
        KAFKA_MEDA --> MEDA_DAG
        MCZ_DAG --> MCZ_CALIB
        MEDA_DAG --> MEDA_CALIB
        MCZ_DAG --> DBT
        MEDA_DAG --> DBT
        MCZ_DAG --> LAKE
        MEDA_DAG --> LAKE
        MCZ_DAG --> PG
        MEDA_DAG --> PG
    end
    subgraph VIZ["📊 Visualización"]
        GRAFANA["Grafana"]
        JUPYTER["JupyterHub"]
    end
    FPGA --> MRO
    MEDA_FPGA --> MRO
    DSN --> EDR
    EDR -.simulado vía.-> KAFKA_MCZ
    EDR -.simulado vía.-> KAFKA_MEDA
    PG --> GRAFANA
    LAKE --> JUPYTER
```

*(Ver [sección Cloud (AWS)](#cloud-aws--stack-moderno-con-crédito-de-estudiante) para la variante de despliegue en AWS.)*

---

## Results — Live System

El diagrama de arriba es la promesa; esto es la prueba de que el sistema corre de punta a punta, con datos generados por el propio simulador, pasando por Kafka, Airflow, dbt y Postgres hasta llegar a un dashboard real.

![Demo: flujo de datos Marte-Tierra y el mapa interactivo de flujo de datos](docs/images/demo.gif)

### Grafana — Telemetría MEDA y cobertura Mastcam-Z

![Grafana dashboard: temperatura/presión, curva diurna, viento, cobertura de imágenes y anomalías detectadas](docs/images/grafana_dashboard.png)

5 paneles sobre datos reales generados por el pipeline, no datos de ejemplo:

- **Curva diurna de temperatura** (`lmst_h` en X) — reproduce la forma sinusoidal del modelo físico de MEDA (mínimo pre-amanecer, máximo post-mediodía marciano), no una línea de ejemplo.
- **Temperatura y presión**, **Viento** — series temporales con eje derecho dedicado para la variable de escala distinta, evitando que una aplaste a la otra.
- **Cobertura de imágenes por sol** — la proporción 5:3 entre cámara izquierda/derecha coincide exactamente con el plan de captura real del simulador (wide RGB estéreo, zoom rojo, NIR, azul atmosférico).
- **Anomalías detectadas** — filas marcadas automáticamente por las reglas de `meda_anomaly_rules.py` cuando una lectura cruza el umbral configurado, no una tabla curada a mano.

### Airflow — Orquestación del pipeline MEDA

![Airflow: grafo del DAG meda_full_pipeline](docs/images/airflow_dag_graph.png)

El DAG `meda_full_pipeline` implementa Raw → Bronze (validación) → Silver (calibración + detección de anomalías) → Gold (agregados vía dbt), siguiendo el contrato Medallion de la [constitución del proyecto](.specify/memory/constitution.md): cada capa transforma, ninguna se salta.

---

## Mastcam-Z Camera Specifications

| Parameter | Value |
|-----------|-------|
| CCD format | 1648 × 1214 pixels |
| Pixel size | 7.4 µm × 7.4 µm |
| Bit depth | 12-bit (DN 0–4095) |
| Focal length | 26–110 mm (4:1 zoom) |
| FOV (wide) | 25.6° × 19.2° |
| FOV (tele) | 6.2° × 4.6° |
| Filter positions | 8 per camera (16 total) |
| Spectral range | 400–1012 nm |
| Stereo baseline | 24.3 cm (Left to Right) |
| Compression | ICER (lossy) / Lossless |
| APID Left | 0x01A5 |
| APID Right | 0x01A6 |

### Filter Wheel Configuration

| Position | Left Camera | λ (nm) | Right Camera | λ (nm) |
|----------|-------------|--------|--------------|--------|
| 0 | L0 Broadband RGB | 530 | R0 Broadband RGB | 530 |
| 1 | L1 Blue | 445 | R1 NIR-480 | 480 |
| 2 | L2 Green | 527 | R2 Green | 530 |
| 3 | L3 Red | 676 | R3 Red | 630 |
| 4 | L4 NIR-800 | 800 | R4 NIR-800 | 800 |
| 5 | L5 NIR-866 | 866 | R5 NIR-908 | 908 |
| 6 | L6 NIR-910 | 910 | R6 NIR-937 | 937 |
| 7 | L7 NIR-939 | 939 | R7 SWIR-1012 | 1012 |

*Reference: Bell et al. 2021, Space Science Reviews 217:24*

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Rover simulator | Python 3.11 + NumPy + Pillow | Mastcam-Z image + metadata generation |
| CCSDS encoder | Python (custom) | CCSDS 133.0-B-2 space packet protocol |
| Telemetry | Python + MEDA model | Temperature, pressure, wind, dust τ |
| Messaging | Apache Kafka 7.6 | CCSDS channel + light-delay simulation |
| Data lake | MinIO (S3-compatible) / Amazon S3 | Bronze / Silver / Gold layers, local o AWS |
| ETL orchestration | Apache Airflow 2.9 | Medallion pipeline DAG (10 tasks, incl. dbt) |
| Transformación declarativa | dbt-core 1.8 (Postgres) | Staging + marts, tests, docs/lineage |
| Spatial database | PostgreSQL 16 + PostGIS 3.4 (local o Amazon RDS) | Image footprints + rover traverse |
| Monitoring | Grafana 10 | Telemetry time-series dashboards |
| Analysis | JupyterHub + SciPy | Notebooks + ML models |
| Infrastructure | Docker Compose | Full local deployment |
| CI/CD | GitHub Actions | Lint, tests, dbt build, docker build |
| Cloud / IaC | AWS (S3, RDS, EC2, Lambda, Glue/Athena, SNS, SSM, CloudFront) + Terraform | Ver [sección Cloud (AWS)](#cloud-aws--stack-moderno-con-crédito-de-estudiante) |

---

## Project Structure

```
rover_mars/
├── docker-compose.yml           # Stack local completo
├── docker-compose.aws.yml       # Variante EC2 + RDS + S3 (Opción C)
├── .env.example                 # Plantilla de variables de entorno
├── Makefile                     # make up / test / dbt-run / tf-plan ...
├── common/rovermars_common/     # Código compartido (cliente S3/MinIO único, ver Fase 7)
│   └── storage.py
├── simulator/
│   ├── mastcamz_simulator.py    # Camera + PDS4 label generator
│   ├── telemetry_generator.py   # MEDA-like environment model
│   ├── ccsds_encoder.py         # CCSDS 133.0-B-2 protocol
│   └── Dockerfile               # Build context = raíz del repo (usa common/)
├── ingestion/
│   ├── dsn_receiver.py          # Kafka → Bronze layer (DSN simulation)
│   └── Dockerfile               # Build context = raíz del repo (usa common/)
├── airflow/
│   ├── dags/mastcamz_pipeline.py# Full ETL DAG (Bronze→Silver→Gold + dbt_build)
│   ├── plugins/calibration.py   # Matemática de calibración (testeada aparte)
│   ├── plugins/anomaly_rules.py # Reglas de anomalía (testeadas aparte, Fase 7)
│   ├── plugins/kafka_offsets.py # Bookkeeping de offsets Kafka (testeado, Fase 7)
│   └── Dockerfile               # Imagen Airflow + dbt-core + drivers (usa common/)
├── dbt/                         # Transformación declarativa (ADR-001)
│   ├── models/staging/
│   ├── models/marts/
│   └── seeds/dsn_stations.csv
├── tests/                       # pytest — CCSDS, calibración, telemetría
├── .github/workflows/           # CI: lint, tests, dbt build, docker build
├── infra/aws/                   # Terraform — S3, RDS, EC2, Lambda, Glue/Athena...
├── database/
│   ├── init.sql                 # PostgreSQL + PostGIS setup
│   └── schema.sql               # Tables, views, spatial functions
├── dashboard/
│   └── index.html               # Interactive architecture dashboard
├── docs/                        # ADRs, guía de implementación, drafts/
├── notebooks/
└── data/                        # raw/ bronze/ silver/ gold/ (gitignored)
```

---

## Data Pipeline — Medallion Architecture

### RAW Layer (MinIO: `mastcamz-raw`)
- Binary `.IMG` files (12-bit CCD data, big-endian)
- PDS4 XML labels per image
- Immutable — never modified after arrival

### BRONZE Layer (MinIO: `mastcamz-bronze`)
- Validated and catalogued JSON metadata
- CRC-16/CCITT integrity verified
- DSN station stamped, light-delay recorded
- Indexed in PostgreSQL `image_products` table

### SILVER Layer (MinIO: `mastcamz-silver`)
- Radiometrically calibrated:
  - Bias subtraction (DN − 2047)
  - Dark current correction
  - Flat-field per filter
  - DN → I/F conversion
- Geometric calibration (CAHVOR camera model)
- Stereo disparity map (24.3 cm baseline)
- PostGIS image footprint polygon

### GOLD Layer (MinIO: `mastcamz-gold`)
- Sol-level aggregate statistics
- Multispectral composite summary
- Rover traverse GeoJSON path
- Dust storm event flags
- Grafana-ready time-series

---

## Airflow DAG Tasks

```
start_pipeline
    └── poll_bronze_queue         (Kafka consumer, up to 50 events)
         └── validate_raw_products (PDS4 + CRC check)
              └── radiometric_calibration (Bias/Dark/Flat/IOF)
                   └── geometric_calibration (CAHVOR model)
                        └── write_silver_layer (MinIO/S3 silver)
                             ├── update_postgis (image footprint upsert)
                             │        └── dbt_build (staging + marts + tests, ver dbt/)
                             └── anomaly_detection (dust storms, alerts)
                                  └── build_gold_aggregates (sol stats)
                                       ├──────────────┐
                                       └── notify_science_team ← dbt_build
                                            └── end_pipeline
```

La matemática de calibración (radiometric/geometric) vive en [airflow/plugins/calibration.py](airflow/plugins/calibration.py) — funciones puras, cubiertas por [tests/test_calibration.py](tests/test_calibration.py), independientes de Airflow.

---

## Communication Chain (Simulated)

| Leg | Protocol | Data Rate | Delay |
|-----|----------|-----------|-------|
| Rover → MRO | UHF 437 MHz | ~2 Mbps | ~8 min/sol window |
| MRO → DSN | X-Band 8.4 GHz | up to 100 Mbps | 3–22 min (light time) |
| DSN → JPL | Fiber (TDRS) | 100+ Mbps | seconds |
| Kafka simulation | Local TCP | unlimited | configurable delay |

### DSN Ground Stations Simulated
- **Goldstone, California** — DSS-14 (70m), primary Mars link
- **Madrid, Spain** — DSS-63 (70m)
- **Canberra, Australia** — DSS-43 (70m)

### CCSDS Space Packet (CCSDS 133.0-B-2)
```
Primary Header (6 bytes):
  VER(3) | TYPE(1) | SHF(1) | APID(11) | SEQ_FLAGS(2) | SEQ_COUNT(14) | DATA_LEN(16)

Secondary Header (16 bytes, simulation):
  SCLK(8) | SOL(4) | WAVELENGTH_NM(2) | CRC16(2)
```

---

## Mars Environment Model

The telemetry generator replicates MEDA (Mars Environmental Dynamics Analyzer) measurements:

| Parameter | Range | Model |
|-----------|-------|-------|
| Surface temperature | −120 to +50 °C | Diurnal + seasonal |
| Air temperature (1m) | −120 to +30 °C | T_surface − 20°C |
| Atmospheric pressure | 600–850 Pa | Seasonal CO₂ cycle |
| Wind speed | 0–25 m/s | Gaussian + seasonal |
| Dust opacity τ | 0.3–8.0 | Storm probability model |
| UV index | 0–6 | Perihelion-scaled |
| MMRTG output | 110 → 95 W | 4.8%/year RTG decay |
| Light travel time | 3–22 min | Synodic orbit model |

---

## Quick Start

### Prerequisites
- Docker 24+ and Docker Compose v2
- Python 3.11+ (for standalone simulator)
- 8 GB RAM minimum (16 GB recommended)

### Deploy All Services

```bash
# Clone the repository
git clone https://github.com/javiladino/rover_mars
cd rover_mars

# Copy the env template and set your own credentials (.env is gitignored)
cp .env.example .env
# Generate a real Airflow Fernet key and paste it into .env:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Launch all Docker services (equivalente a: make up)
docker compose up --build -d

# Monitor startup
docker compose ps
```

Guía completa paso a paso (incluye dbt, tests, CI/CD y despliegue en AWS): [docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md](docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md)

### Access Services

Credenciales: definidas en tu `.env` (ver `.env.example`), nunca hardcodeadas en el repo.

| Service | URL | Credentials |
|---------|-----|-------------|
| Airflow | http://localhost:8080 | `$AIRFLOW_ADMIN_USER` / `$AIRFLOW_ADMIN_PASSWORD` |
| MinIO | http://localhost:9001 | `$MINIO_ACCESS_KEY` / `$MINIO_SECRET_KEY` |
| Grafana | http://localhost:3001 | `$GRAFANA_ADMIN_USER` / `$GRAFANA_ADMIN_PASSWORD` |
| JupyterHub | http://localhost:8888 | token: `$JUPYTER_TOKEN` |
| Kafka UI | http://localhost:8085 | — |
| dbt docs | http://localhost:8081 | `make dbt-docs` |
| Dashboard | [dashboard/index.html](dashboard/index.html) | — |

### Run Simulator Standalone

```bash
cd simulator
pip install -r requirements.txt

KAFKA_BOOTSTRAP=localhost:29092 \
MINIO_ENDPOINT=http://localhost:9000 \
SIMULATION_TOTAL_SOLS=20 \
SIMULATION_INTERVAL_SEC=5 \
python mastcamz_simulator.py
```

### Useful Queries

```sql
-- Image coverage per sol
SELECT * FROM science.sol_filter_coverage;

-- Rover traverse path (GeoJSON)
SELECT sol, ST_AsGeoJSON(rover_location) FROM science.rover_traverse;

-- Dust storm events (τ > 2.0)
SELECT * FROM science.dust_storm_events;

-- Full telemetry time-series (Grafana source)
SELECT * FROM science.telemetry_timeseries WHERE time > NOW() - INTERVAL '7 days';
```

---

## PDS4 Product ID Format

```
urn:nasa:pds:mars2020_mastcamz_sci_raw:data_imagedr:M20_MCZL_0001_0000700032_000RZL_N_01
                                                     │    │    │    │          │   │   │
                                                     │    │    │    │          │   │   └─ Version
                                                     │    │    │    │          │   └─── N=Normal
                                                     │    │    │    │          └─────── RZL=Raw Zoom Left
                                                     │    │    │    └────────────────── SCLK (10 digits)
                                                     │    │    └─────────────────────── Sol number
                                                     │    └──────────────────────────── MCZL=Left / MCZR=Right
                                                     └───────────────────────────────── Mission prefix
```

---

## Modern Data Stack

Además del pipeline de ingesta/orquestación, el proyecto incorpora las piezas que
hoy se esperan de un rol de Data Engineer más allá del ETL:

| Pieza | Dónde | Comando |
|---|---|---|
| Transformación declarativa (dbt) | [`dbt/`](dbt/) — staging + marts, tests, seeds | `make dbt-run` / `make dbt-test` |
| Tests unitarios | [`tests/`](tests/) — CCSDS, calibración, telemetría | `make test` |
| Lint | ruff | `make lint` |
| CI/CD | [`.github/workflows/`](.github/workflows/) | lint, tests, dbt build, docker build en cada push/PR |
| Infra as Code | [`infra/aws/`](infra/aws/) — Terraform | `make tf-plan` |

Todas las decisiones de arquitectura detrás de estas piezas están documentadas
como ADRs en [docs/ANALISIS_MODERN_DATA_STACK.md](docs/ANALISIS_MODERN_DATA_STACK.md),
y la implementación paso a paso en [docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md](docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md).

---

## Cloud (AWS) — stack moderno con crédito de estudiante

El stack también puede desplegarse combinando cómputo self-managed con
servicios gestionados de AWS, adoptados selectivamente según su costo real
frente a un crédito de estudiante limitado (ADR-011 a ADR-020 en el
análisis de arquitectura):

```mermaid
flowchart TB
    subgraph EC2["EC2 — Airflow + Kafka self-managed"]
        A[Airflow]
        K[Kafka]
    end
    subgraph AWS["Servicios gestionados AWS"]
        S3[(S3 — data lake)]
        RDS[(RDS PostgreSQL+PostGIS)]
        GLUE[Glue + Athena]
        LAMBDA[Lambda]
        SNS[SNS — alertas]
        CF[CloudFront + S3 — demo estática]
    end
    A --> S3
    A --> RDS
    S3 --> GLUE
    S3 -- evento --> LAMBDA
    A -. anomalía .-> SNS
    CF -. landing pública .-> S3
```

MWAA (Airflow gestionado) y MSK (Kafka gestionado) se evaluaron y se
descartaron deliberadamente por costo (~300 USD/mes y ~150 USD/mes
respectivamente) — el detalle de esa decisión está en ADR-014. Todo el
despliegue está provisionado con Terraform en [`infra/aws/`](infra/aws/README.md)
y documentado paso a paso en la Fase 4 de la guía de implementación.

---

## Future Extensions

- **CesiumJS 3D Mars map** — Rover traverse on MOLA terrain model
- **ML terrain classification** — Detect basalt/carbonate/olivine from multispectral
- **Anomaly detection model** — Isolation Forest on MEDA sensor stream
- **Cité de l'Espace installation** — 360° dome visualization prototype
- **ESA ExoMars integration** — Raman spectrometer data pipeline
- **Real PDS4 data ingestion** — ASU/NASA Mastcam-Z public archive

---

## References

- Bell et al. (2021). *The Mars 2020 Perseverance Rover Mast Camera Zoom (Mastcam-Z) Investigation*. Space Science Reviews 217:24. [DOI 10.1007/s11214-020-00755-x](https://doi.org/10.1007/s11214-020-00755-x)
- Hayes et al. (2021). *Pre-Flight Calibration of Mastcam-Z*. Space Science Reviews 217:40.
- CCSDS (2012). *Space Packet Protocol*. Recommendation CCSDS 133.0-B-2.
- NASA PDS4 Standards Reference. https://pds.nasa.gov/pds4/doc/sr/
- NASA DSN 810-005 Telecommunications Link Design Handbook.
- Mastcam-Z PDS4 Archive (DOI 10.17189/q3ts-c749). https://mastcamz.asu.edu/mastcam-z-data-for-all/

---

## ¿No eres técnico? (reclutadores / RRHH)

Este proyecto es una réplica funcional, construida de extremo a extremo, del
sistema que la NASA usa para recibir y procesar las fotos y datos ambientales
del rover Perseverance en Marte — no un ejercicio de curso, sino la
simulación de un problema real de ingeniería de datos, con el mismo estándar
(pruebas automáticas, control de costos en la nube, documentación de
decisiones) que usaría un equipo profesional. Una explicación de 2 minutos,
sin jerga técnica, está en la [sección 10 de la guía de implementación](docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md#10-explicación-para-perfiles-no-técnicos-cierre-de-la-guía).

**¿Qué hace el sistema, en 6 pasos?**

```mermaid
flowchart LR
    A["🤖 Rover en Marte<br/>Saca fotos y mide<br/>clima (temp., viento,<br/>presión)"]
    B["📡 Cruza el espacio<br/>La señal viaja<br/>3 a 22 minutos<br/>hasta la Tierra"]
    C["📥 Llega y se ordena<br/>Cada dato se pone<br/>en una fila de espera<br/>para procesarse"]
    D["🧹 Se limpia y se valida<br/>Se descarta lo dañado,<br/>se corrigen las medidas<br/>con datos de calibración"]
    E["🚨 Revisa si algo anda mal<br/>Detecta automáticamente<br/>lecturas fuera de lo normal,<br/>sin revisión manual"]
    F["📊 Tablero listo<br/>Gráficos y alertas<br/>para tomar decisiones"]
    A --> B --> C --> D --> E --> F
```

*(El diagrama técnico completo, con los nombres reales de cada pieza del stack, está en la [sección Architecture Overview](#architecture-overview).)*

---

## Contact

Javier Ladino · Data Engineer
[javier.ladino.moreno@gmail.com](mailto:javier.ladino.moreno@gmail.com)

> *"Exploring Mars, building from Earth."*
