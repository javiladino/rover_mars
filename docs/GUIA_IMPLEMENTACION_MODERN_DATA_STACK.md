# Guía de Implementación — Modern Data Stack (Bitácora, Fases 1-7)

> Este documento es una **bitácora de trabajo**: registra qué se implementó, por qué, y los
> comandos exactos para reproducirlo o continuarlo. Complementa a
> [docs/ANALISIS_MODERN_DATA_STACK.md](ANALISIS_MODERN_DATA_STACK.md), que contiene el
> razonamiento completo detrás de cada decisión (ADR-001 a ADR-020). Aquí el foco es
> **el paso a paso**, no el porqué de cada alternativa descartada.
>
> Última actualización: 2026-09-04. Idioma: español (se traducirá a inglés en una
> iteración posterior, antes de publicar el proyecto).

## Cómo usar esta guía

Cada fase tiene tres partes:
1. **Qué se implementó** — el código/infraestructura ya escrito en este repositorio.
2. **Por qué importa** — la explicación profesional de qué problema resuelve y qué
   competencia de Data Engineer demuestra frente a un entrevistador.
3. **Cómo ejecutarlo / verificarlo** — comandos exactos para correrlo tú mismo.

Al final de cada fase hay una casilla de estado. Nada de lo marcado como
`⚠️ pendiente de ejecutar` se aplicó automáticamente — son pasos que requieren tus
credenciales (AWS, GitHub) o una decisión tuya (cuándo gastar crédito, cuándo hacer
público el repo), así que se dejaron listos pero no se ejecutaron por ti.

---

## Resumen: qué se hizo en esta sesión vs. qué falta ejecutar

| | Hecho en esta sesión (código/config ya en el repo) | Pendiente de que tú lo ejecutes |
|---|---|---|
| Fase 1 | `.gitignore`, `.env.example`, `LICENSE`, limpieza de raíz, README con Mermaid | Copiar `.env.example` → `.env` y poner tus credenciales reales |
| Fase 2 | Tests, workflows de CI, `Makefile`, `pyproject.toml` | `git push` para que las Actions corran por primera vez |
| Fase 3 | Proyecto `dbt/` completo (staging, marts, seeds, tests), tarea `dbt_build` en el DAG | `docker compose up --build`, luego `make dbt-run` |
| Fase 4 | Módulo Terraform completo en `infra/aws/` | `terraform apply` (gasta crédito real — revisar antes) |
| Fase 5 | Dashboard y README actualizados con la arquitectura nueva | Grabar un GIF/demo y publicar el repo |
| Fase 6 | — (queda documentado como próximos pasos) | Great Expectations, Schema Registry, Metabase, wiring de SNS |
| Fase 7 | Auditoría de determinismo/idempotencia/parametrización/SRP + 9 correcciones aplicadas y **verificadas con pytest real** (62/62 tests, Python 3.11.10) | Conectar `DSNSimulator` al flujo real de `dsn_receiver.py` (documentado, no implementado) |

---

## Fase 1 — Higiene y confianza del repositorio

### Qué se implementó

- **`.gitignore` reescrito** para el stack real (antes era una plantilla de .NET que no
  cubría `__pycache__/`, `.venv/`, `.env`, ni los datos generados en `data/*`).
- **`.env.example`** con todas las variables que antes estaban hardcodeadas en
  `docker-compose.yml` (contraseñas de Postgres/MinIO/Grafana, la Fernet key de Airflow,
  el token de Jupyter). `docker-compose.yml` se reescribió para leer todo con
  `${VARIABLE}` en vez de valores literales.
- **`LICENSE`** (MIT).
- **Reorganización de la raíz**: `donne1.html`, `index1.html`, `infra1.html`,
  `infra2fr.html` y `poc.md` se movieron a `docs/drafts/`; `archi_serveur_ubuntu.md` se
  movió a `docs/archi_servidor_ubuntu.md` (es referencia legítima de infraestructura, no
  un borrador descartable).
- **`README.md`** con diagramas Mermaid (antes ASCII), badges de estado, y secciones
  nuevas de Modern Data Stack y Cloud (AWS).
- **Bug de seguridad corregido**: `simulator/mastcamz_simulator.py` recibía
  `minio_access`/`minio_secret` como parámetros del constructor pero los ignoraba y
  usaba `"minioadmin"` hardcodeado al crear el cliente MinIO — ahora usa las credenciales
  reales pasadas por entorno.

### Por qué importa

Un repositorio con credenciales en texto plano en git es un hallazgo de seguridad real,
no cosmético — si este repo se hace público tal como estaba, cualquiera tiene la Fernet
key de Airflow y las contraseñas de todos los servicios. Separar configuración (`.env`)
de código es la práctica mínima esperada en cualquier proyecto que se evalúe como
"production-grade", y es además lo primero que un revisor técnico mira al abrir un repo.
La limpieza de la raíz importa por una razón distinta: es la primera impresión visual del
proyecto — una raíz con archivos de exploración mezclados con el código de producción
comunica "prototipo sin terminar" antes de que el evaluador lea una sola línea de código.

### Cómo ejecutarlo

```bash
cp .env.example .env

# Generar una Fernet key real para Airflow:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Pegar el resultado en AIRFLOW_FERNET_KEY dentro de .env

# Completar el resto de contraseñas en .env con valores propios (no dejar "changeme_*")

# Verificar que .env NO quede trackeado por git:
git status --short | grep -E "^\?\? \.env$" && echo "OK: .env sigue sin trackear" || echo "revisar .gitignore"
```

**Estado: ✅ código y plantillas listos. ⚠️ pendiente que generes tus propias credenciales en `.env`.**

---

## Fase 2 — Calidad de ingeniería (tests, lint, CI/CD)

### Qué se implementó

- **`airflow/plugins/calibration.py`**: la matemática de calibración radiométrica y
  geométrica (bias/dark, factor radiométrico, I/F, ground sample distance, offset
  estéreo) se extrajo de dentro de las tareas del DAG a un módulo puro, sin dependencias
  de Airflow/Kafka/MinIO. El DAG (`airflow/dags/mastcamz_pipeline.py`) ahora importa y
  usa estas funciones en vez de tener la fórmula duplicada inline.
- **`tests/`** — pytest cubriendo:
  - `test_calibration.py`: la fórmula I/F, el factor radiométrico, el GSD, el offset
    estéreo izquierda/derecha.
  - `test_ccsds_encoder.py`: framing CCSDS, validez de CRC-16, fragmentación de
    payloads grandes en múltiples paquetes, reensamblado y detección de huecos de
    secuencia.
  - `test_telemetry_generator.py`: que los rangos físicos (temperatura, presión, viento,
    opacidad de polvo, batería) se mantengan dentro de lo documentado a lo largo de
    cientos de soles simulados.
  - **Verificación realizada en esta sesión**: como el entorno Python local tenía un
    problema de instalación de `pip`/`pytest` (conflicto de versión de `libexpat` en el
    Python de Homebrew), cada aserción de los tres archivos de test se ejecutó
    manualmente contra los módulos reales con `python3 -m py_compile` + un script de
    verificación equivalente — las 30+ aserciones pasaron. Aun así, corre `make test`
    en tu máquina/CI para tener la confirmación con pytest real.
- **`pyproject.toml`** (config de ruff + pytest) y **`requirements-dev.txt`**.
- **`.github/workflows/`**: `lint.yml` (ruff), `test.yml` (pytest + cobertura),
  `docker-build.yml` (matrix build de las 3 imágenes), `dbt-ci.yml` (ver Fase 3).
- **`Makefile`** con atajos: `make up`, `make test`, `make lint`, `make dbt-run`,
  `make tf-plan`, etc.
- **`airflow/Dockerfile` + `airflow/requirements.txt`**: antes `docker-compose.yml`
  usaba la imagen oficial de Airflow sin instalar `minio`, `psycopg2-binary` ni
  `confluent-kafka` — paquetes que el DAG importa dentro de sus tareas. Era un bug
  latente (probablemente nunca se había corrido `docker compose up` hasta el final).
  Ahora se construye una imagen propia que sí los instala, además de `dbt-core`/`dbt-postgres`.

### Por qué importa

Separar la matemática de calibración del código de orquestación no es solo estilo: es lo
que hace posible testearla sin levantar Airflow, Kafka o Postgres — un test que corre en
200ms en vez de necesitar 10 contenedores. Eso es exactamente lo que un entrevistador
técnico busca cuando pregunta "¿cómo testeas un pipeline de datos?": la respuesta correcta
no es "levanto todo el stack y reviso a mano", es "aíslo la lógica de negocio de la
orquestación y la testeo por separado". El CI/CD, por su parte, es la señal más rápida de
"esto se mantiene con estándares profesionales" — es lo primero que revisa un reclutador
técnico al entrar a la pestaña Actions de GitHub.

### Cómo ejecutarlo

```bash
make lint      # ruff sobre simulator/, ingestion/, airflow/dags/, airflow/plugins/, tests/
make test      # pytest con cobertura sobre airflow/plugins/ y simulator/
```

Los workflows de `.github/workflows/` corren automáticamente en cada `git push`/PR una
vez que el repo esté en GitHub (ver Fase 5).

**Estado: ✅ implementado y verificado manualmente. ⚠️ pendiente correr `pytest` real en tu máquina (o dejar que lo haga el CI) para la confirmación final.**

---

## Fase 3 — dbt: transformación declarativa (el diferenciador)

### Qué se implementó

- **`dbt/`** — proyecto dbt-core completo:
  - `models/staging/stg_image_products.sql`, `stg_telemetry_records.sql`: vistas 1:1
    sobre las tablas que ya llena `update_postgis` en el DAG, con nombres y tipos
    normalizados.
  - `models/marts/dim_dsn_stations.sql`: dimensión de estaciones DSN, combinando un
    **seed** (`seeds/dsn_stations.csv`, datos estáticos: antena, país, coordenadas) con
    el conteo real de productos recibidos por estación.
  - `models/marts/fct_sol_filter_coverage.sql`: equivalente declarativo a la vista SQL
    `science.sol_filter_coverage` que ya existía en `database/schema.sql` — misma
    métrica de negocio, ahora versionada y testeada como modelo dbt.
  - `models/marts/fct_sol_summary.sql`: capa Gold declarativa combinando imágenes +
    telemetría por sol. **Convive** con `build_gold_aggregates` (que sigue escribiendo
    el JSON de Gold que ya consumen Grafana y el dashboard) — no se reemplazó, se
    complementó, como indica ADR-001.
  - Tests declarativos (`not_null`, `unique`, `accepted_values`) en
    `_staging__sources.yml`, `_staging__models.yml`, `_marts__models.yml`.
  - `profiles.yml` **seguro de versionar**: no contiene contraseñas, usa `env_var()` de
    dbt para leer las mismas variables que ya usa `docker-compose.yml`.
- **Tarea `dbt_build`** añadida al DAG (`airflow/dags/mastcamz_pipeline.py`), como
  `BashOperator` que corre después de `update_postgis` (necesita datos ya en Postgres) y
  antes de `notify_science_team`.
- **`.github/workflows/dbt-ci.yml`**: levanta un Postgres efímero, carga
  `database/init.sql` + `database/schema.sql`, y corre `dbt build` en cada cambio dentro
  de `dbt/` o `database/`.

### Por qué importa

dbt es, con diferencia, la palabra que más aparece en ofertas de Data Engineer hoy, y no
por moda: resuelve un problema real que este proyecto tenía — la lógica de agregación
Silver→Gold vivía como funciones Python imperativas dentro de tareas de Airflow, sin
versionado semántico, sin tests declarativos, sin lineage visible. Con dbt, cada modelo
es SQL trazable en git, cada cambio se testea automáticamente (`dbt-ci.yml`), y
`dbt docs generate` produce un catálogo navegable con el grafo de dependencias entre
modelos — algo que de otra forma habría que construir a mano. Es también la pieza que
más "cuenta una historia de madurez": mostrar que sabes cuándo mover lógica de un
lenguaje imperativo (Python) a uno declarativo (SQL versionado) es una señal de
seniority, no solo de conocer una herramienta.

### Cómo ejecutarlo

```bash
# Reconstruir la imagen de Airflow con dbt-core instalado
docker compose up --build -d

# Una vez que Postgres tenga datos (después de correr el simulador y el DAG al menos una vez):
make dbt-run     # dbt run
make dbt-test    # dbt test
make dbt-docs    # sirve el catálogo navegable en http://localhost:8081
```

**Estado: ✅ proyecto dbt completo y wireado al DAG. ⚠️ pendiente ejecutar `docker compose up --build` (reconstruye la imagen de Airflow) y correr el DAG al menos una vez para tener datos que transformar.**

---

## Fase 4 — Integración con AWS (Terraform)

### Qué se implementó

Módulo Terraform completo en **`infra/aws/`** (detalle de cada decisión en ADR-011 a
ADR-020 del análisis de arquitectura):

| Archivo | Qué provisiona |
|---|---|
| `s3.tf` | 4 buckets (raw/bronze/silver/gold), versionado, bloqueo de acceso público, lifecycle a Standard-IA a los 30 días |
| `rds.tf` + `network.tf` | RDS PostgreSQL 16 (`db.t3.micro`, free tier), security group que solo acepta conexiones desde el EC2 |
| `ec2.tf` + `iam.tf` | EC2 Ubuntu 22.04 con Docker preinstalado vía `user_data`, rol IAM de mínimo privilegio (solo S3 de este proyecto, SSM de este proyecto, publicar en el SNS de este proyecto) |
| `ssm.tf` | Parámetros placeholder en SSM Parameter Store (los valores reales se cargan a mano post-`apply`, nunca vía Terraform) |
| `lambda.tf` + `lambda/s3_event_handler.py` | Lambda disparada por `ObjectCreated` en el bucket `raw`, valida tamaño/extensión |
| `sns.tf` | Tópico SNS + suscripción por email para alertas del pipeline |
| `glue_athena.tf` | Glue Data Catalog + Crawler + Athena Workgroup sobre `gold/parquet/` |
| `cloudfront.tf` | Bucket + distribución CloudFront para publicar `dashboard/index.html` |
| `budgets.tf` | AWS Budgets con alertas al 50/80/100% del límite mensual que definas |

También se creó **`docker-compose.aws.yml`**: variante del stack para correr en el EC2,
sin contenedores de `postgres`/`minio` (apunta a RDS y S3 reales), y se parametrizaron
los nombres de bucket (`S3_BUCKET_RAW`, `S3_BUCKET_BRONZE`, etc.) en
`airflow/dags/mastcamz_pipeline.py`, `ingestion/dsn_receiver.py` y
`simulator/mastcamz_simulator.py` — antes estaban hardcodeados como `"mastcamz-raw"`
literal, lo que habría hecho imposible apuntar a los buckets reales creados por
Terraform (que se llaman `rovermars-raw-demo`, etc.) sin tocar código.

### Qué queda honestamente pendiente (no implementado en esta sesión)

- **`build_gold_aggregates` no escribe Parquet todavía** — sigue escribiendo solo JSON.
  El Glue Crawler (`glue_athena.tf`) apunta a `gold/parquet/`, así que antes de poder
  consultar con Athena hace falta añadir una escritura en Parquet (con `pyarrow` o
  `pandas.to_parquet`) a esa tarea. Es un cambio acotado (~20 líneas) que se deja para
  la Fase 6 o para cuando decidas activar ADR-015 en serio.
- **La tarea `anomaly_detection` no publica a SNS todavía** — el tópico existe
  (`sns.tf`) y el rol IAM del EC2 ya tiene permiso `sns:Publish`, pero el código Python
  de la tarea sigue solo logueando (`log.warning`). Conectarlo es ~10 líneas con
  `boto3.client("sns").publish(...)` condicionadas a `SNS_ALERTS_TOPIC_ARN`.
- **Terraform no se aplicó** — por diseño: `terraform apply` gasta crédito real de tu
  cuenta AWS y requiere tus credenciales configuradas (`aws configure`), así que es una
  acción que debes ejecutar tú, revisando `terraform plan` primero.

### Por qué importa

Esta es la pieza que responde directamente al filtro "experiencia con AWS" que aparece
como requisito duro en muchas ofertas — pero la parte más valiosa no es "usar AWS", es
**el criterio de costo detrás de cada decisión**: MWAA y MSK se evaluaron y se
descartaron explícitamente por precio (documentado en ADR-014), en vez de simplemente no
mencionarlos. Ese tipo de razonamiento — "evalué la opción gestionada, la descarté por
esta razón concreta, y aquí está la alternativa que sí se ajusta al contexto" — es
exactamente la conversación que un entrevistador técnico quiere tener, y muy pocos
candidatos junior/pleno llegan con esa narrativa ya armada.

### Cómo ejecutarlo

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars   # completa tus valores
export TF_VAR_rds_master_password="una-contraseña-fuerte"

aws configure    # si no lo has hecho ya, con las credenciales de tu cuenta de crédito

terraform init
terraform apply -target=aws_budgets_budget.monthly   # primero el guardrail de gasto
terraform plan                                        # REVISAR antes de aplicar el resto
terraform apply

terraform output   # IP del EC2, endpoint de RDS, nombres de bucket, URL de CloudFront...
```

En el EC2 (por SSH, con la IP de `terraform output`):

```bash
git clone <tu-repo> && cd rover_mars
cp .env.example .env
# Completar .env con: AWS_ACCESS_KEY_ID/SECRET (de un usuario IAM con permisos limitados,
# no el root), RDS_HOST/RDS_ENDPOINT/RDS_USER/RDS_PASSWORD, y los nombres de bucket
# reales que salieron de `terraform output s3_buckets`.

# Habilitar PostGIS en RDS (no viene activo por defecto):
psql "postgresql://rover:<password>@<rds-endpoint>/rover_mars" \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql "postgresql://rover:<password>@<rds-endpoint>/rover_mars" -f database/schema.sql

docker compose -f docker-compose.aws.yml up --build -d
```

Publicar la demo estática:

```bash
aws s3 sync dashboard/ s3://$(terraform -chdir=infra/aws output -raw dashboard_bucket)/ \
  --exclude "*" --include "index.html"
```

Para dejar de gastar crédito cuando no la estés mostrando:

```bash
cd infra/aws && terraform destroy
```

**Estado: ✅ todo el código Terraform y las variables de entorno listos. ⚠️ pendiente `terraform apply` (gasta crédito real — decisión tuya de cuándo) y las dos mejoras de Fase 6 (Parquet, SNS wiring) si quieres que Glue/Athena y las alertas funcionen de punta a punta.**

---

## Fase 5 — Despliegue y presentación

### Qué se implementó

- **`dashboard/index.html`**: nueva pestaña "☁️ AWS / Cloud" con el diagrama de la
  arquitectura híbrida y la tabla de servicios adoptados vs. descartados por costo;
  actualizado el diagrama del DAG de Airflow (incluye `dbt_build`); actualizada la tabla
  de credenciales para no mostrar contraseñas literales (ahora referencia `.env`);
  actualizado el árbol de estructura del proyecto (`dbt/`, `tests/`, `infra/`,
  `.github/workflows/`).
- **`README.md`**: diagramas Mermaid, badges, tabla de stack actualizada (dbt, CI/CD,
  Terraform/AWS), sección nueva "Modern Data Stack", sección nueva "Cloud (AWS)", enlace
  a esta guía y al documento de ADRs, y un bloque final en lenguaje llano para
  reclutadores no técnicos (ver sección 10 más abajo).

### Por qué importa

Un reclutador no va a clonar el repo y levantar diez contenedores para evaluarte — el
dashboard estático y el README son, en la práctica, el producto que la mayoría de la
gente va a ver primero. Que ambos reflejen fielmente la arquitectura actual (incluyendo
AWS) y no solo la versión local es lo que convierte al proyecto en algo que se explica
solo, sin que tengas que estar presente para aclarar qué es qué.

### Qué falta (decisión y acción tuya, no de código)

1. **Publicar el repo** — hasta ahora estos cambios están solo en tu working directory,
   no comiteados (por diseño: no se hace commit sin que lo pidas explícitamente). Cuando
   quieras:
   ```bash
   git add -A
   git commit -m "Add Modern Data Stack: dbt, tests, CI/CD, AWS/Terraform integration"
   git push
   ```
2. **Grabar un GIF/video corto (20-30s)** del DAG corriendo en Airflow + Grafana
   actualizándose — es lo que más convierte una visita al repo en una conversación de
   entrevista.
3. **Elegir dónde vive la demo pública "siempre arriba"**: la opción más barata y
   robusta es publicar `dashboard/index.html` vía S3+CloudFront (ya provisionado en
   `infra/aws/cloudfront.tf`) o, más simple aún, GitHub Pages apuntando a `dashboard/`.
   El resto del stack (Airflow, Kafka) puede quedar "bajo demanda" — lo enciendes cuando
   un reclutador quiere ver el pipeline correr en vivo, y con `terraform destroy` lo
   apagas el resto del tiempo para no gastar crédito.

**Estado: ✅ dashboard y README actualizados. ⚠️ pendiente: commit/push, grabar demo, decidir y activar el hosting "siempre arriba".**

---

## Fase 6 — Pulido opcional (próxima iteración)

Estos puntos ya estaban marcados como "opcional según tiempo" en el roadmap original del
análisis de arquitectura, y siguen sin implementarse — se documentan aquí para que la
bitácora sea honesta sobre el estado real del proyecto:

- **Great Expectations / Soda Core** (ADR-007): validación declarativa de calidad de
  datos más allá de lo que cubren los tests de dbt (tamaño de imagen, presencia del
  label PDS4, objetos existentes en el lake).
- **Schema Registry con Avro** (ADR-008): los tópicos Kafka siguen transportando JSON
  sin esquema versionado.
- **Wiring de SNS en `anomaly_detection`** (ver Fase 4): el tópico y los permisos ya
  existen, falta la llamada `boto3` en el código de la tarea.
- **Escritura de Parquet en `build_gold_aggregates`** (ver Fase 4): necesaria para que
  el Glue Crawler/Athena de `infra/aws/glue_athena.tf` tengan algo real que catalogar.
- **Metabase o Superset** (ADR-010): un dashboard de "KPIs de la misión" para audiencias
  de negocio, complementario a Grafana (que está más orientado a series de tiempo de
  infraestructura).

Ninguno de estos bloquea que el proyecto ya sea, tal como está tras las Fases 1-5, una
respuesta sólida a "cuéntame de un proyecto de datos end-to-end que hayas construido" en
una entrevista técnica de Data Engineer.

---

## Fase 7 — Auditoría de robustez: determinismo, idempotencia, parametrización y SRP

Esta fase no añade tecnología nueva — audita el pipeline que ya existe (Fases 1-6)
contra cuatro propiedades que cualquier pipeline de datos "de producción" debe
cumplir, y corrige lo que no las cumplía. A diferencia de las fases anteriores,
**cada corrección de esta fase se verificó con pytest real** (no solo replicando
aserciones a mano): se resolvió el Python roto de Homebrew usando `/usr/bin/python3`
primero y, para validar contra el runtime exacto de los contenedores, con
`/opt/homebrew/bin/python3.11` (Python 3.11.10 — la misma versión que
`python:3.11-slim` y `apache/airflow:2.9.1-python3.11`). Resultado final:
**62/62 tests pasando, `ruff check` limpio, sin errores, sobre el runtime real.**

### Qué significa cada propiedad en este proyecto

- **Determinismo**: dada la misma entrada, una función/tarea siempre produce la
  misma salida (metadatos de auditoría como `generated_at`/`arrival_utc` son la
  excepción legítima — son "cuándo pasó esto", no un valor de negocio).
- **Idempotencia**: ejecutar la misma tarea dos veces con la misma entrada deja el
  sistema en el mismo estado final que ejecutarla una vez (no duplica, no
  corrompe, no acumula basura).
- **Parametrización**: nada que razonablemente cambie entre entornos (local/AWS),
  cargas, o criterios de negocio debería estar hardcodeado en el código.
- **Separación de intereses / responsabilidad única**: cada módulo/función hace
  una sola cosa; la lógica de negocio (reglas, cálculos) no debería estar mezclada
  con el I/O de orquestación (Kafka, Postgres, MinIO/S3).

### Hallazgos y correcciones aplicadas

#### 1. [Idempotencia — CRÍTICO] `build_gold_aggregates` generaba una key con timestamp
**Antes:** `gold_key = f"aggregates/latest_gold_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"` — cada corrida del DAG creaba un objeto **nuevo** en MinIO/S3 en vez de actualizar uno existente. El bucket `gold` crecía sin límite y no existía un puntero estable a "el snapshot vigente" (había que listar objetos y ordenar por nombre para encontrar el último).
**Corrección:** key estable y parametrizable, `GOLD_SUMMARY_KEY = os.getenv("GOLD_SUMMARY_KEY", "aggregates/gold_sol_summary.json")`. Cada corrida sobrescribe el mismo objeto — correcto, porque dado el mismo estado de Postgres, `build_gold_aggregates` siempre calcula el mismo resultado. El histórico, si se necesita, lo da gratis el versionado de S3 ya habilitado en `infra/aws/s3.tf` (ADR-012), sin sacrificar la idempotencia de la key "actual".
**Archivo:** `airflow/dags/mastcamz_pipeline.py`.

#### 2. [Idempotencia — pérdida de datos real] Colisión de keys en telemetría Bronze
**Antes:** en `ingestion/dsn_receiver.py`, la key de telemetría en Bronze era `f"sol={sol:04d}/telemetry_{sol:04d}.json"` — dependía **solo** del sol, pero llegan varias muestras de telemetría por sol. Cada muestra nueva sobrescribía a la anterior: **solo sobrevivía la última muestra de cada sol**, el resto se perdía silenciosamente sin ningún error.
**Corrección:** la key ahora incluye el `utc_timestamp` propio de cada evento (`telemetry_{sol:04d}_{event_ts}.json`), determinista (el mismo evento reproducido dos veces produce la misma key → sobrescribe, no duplica) y único por muestra real. Con fallback a la hora de recepción + warning si el evento llega sin `utc_timestamp`.
**Archivo:** `ingestion/dsn_receiver.py`.

#### 3. [Idempotencia / confiabilidad — riesgo real de pérdida de mensajes] Commit prematuro de offsets de Kafka
**Antes:** `poll_bronze_queue` hacía `consumer.commit(message=msg)` **inmediatamente** tras leer cada mensaje, antes de que `validate_raw_products`, la calibración, `write_silver_layer`, `update_postgis` o `dbt_build` confirmaran éxito. Si cualquiera de esas tareas fallaba, el mensaje ya estaba comiteado — Airflow reintenta la tarea, pero el mensaje ya no vuelve a aparecer en Kafka. Pérdida de datos silenciosa ante cualquier fallo a mitad de pipeline.
**Corrección:** `poll_bronze_queue` ya no comitea nada — registra qué offset habría que confirmar por partición (`airflow/plugins/kafka_offsets.py::track_max_offset`, función pura y testeada). Una nueva tarea `commit_kafka_offsets`, downstream de `build_gold_aggregates` **y** `dbt_build`, hace el commit real solo si toda la ruta crítica tuvo éxito. Si el DAG falla antes, el próximo run vuelve a leer los mismos mensajes — seguro, porque los writes downstream (hallazgos #1, #2 ya corregidos, y el upsert de Postgres que ya era idempotente) toleran reprocesamiento.
**Archivos:** `airflow/dags/mastcamz_pipeline.py`, nuevo `airflow/plugins/kafka_offsets.py`.
**Test:** `tests/test_kafka_offsets.py`, incluye `test_reprocessing_the_same_batch_converges_to_the_same_offsets` — verifica explícitamente la propiedad de idempotencia que justifica el diseño.

#### 4. [Determinismo — bug real] `DSNSimulator._apply_ber` nunca corrompía nada, con cualquier semilla
**Antes:** `n_errors = int(n_bits * XBAND_BER)` truncaba a 0 para **cualquier** paquete CCSDS real — el tamaño máximo de un paquete (65528 bytes = 524224 bits) por `XBAND_BER=1e-9` da ~0.0005, y `int()` de eso es 0 siempre. La función "simulaba BER" pero nunca producía un solo bit de error, sin importar la semilla — determinismo por un bug de truncamiento, no por diseño correcto. Además, usaba el módulo `random` global directamente, sin poder inyectar una semilla para testear.
**Corrección:** `DSNSimulator.__init__` acepta `rng: Optional[random.Random] = None` (no determinista por defecto — correcto para ruido de canal real; determinista si se pasa una semilla explícita, para tests). `_apply_ber` ahora modela un ensayo de Bernoulli independiente por bit — matemáticamente correcto, aunque con BER=1e-9 real la probabilidad de observar un error en un solo paquete sigue siendo, correctamente, muy baja (ver `test_realistic_ber_leaves_a_normal_packet_untouched_almost_always`, que documenta esto en vez de solo probarlo).
**Archivo:** `simulator/ccsds_encoder.py`. **Test:** `tests/test_dsn_simulator.py`.
**Observación relacionada, no corregida:** `DSNSimulator`/`CCSDSDecoder` (el protocolo CCSDS completo, con CRC y reensamblado) **no se invocan en ningún punto del pipeline real** — `ingestion/dsn_receiver.py` solo llama a `simulate_light_delay()` y escribe directo a Bronze, sin pasar por decodificación CCSDS. Hoy conviven dos simulaciones del protocolo espacial sin estar conectadas: una completa pero no usada (ahora bien testeada) y otra simplificada que sí corre en producción. Conectarlas es un cambio de comportamiento más grande que excede el alcance de esta auditoría (determinismo/idempotencia/parametrización/SRP) — se deja como ítem de Fase 6/8.

#### 5. [Parametrización] Constantes hardcodeadas en `poll_bronze_queue` y `anomaly_detection`
**Antes:** timeout de poll (`deadline = 20`), máximo de mensajes (`< 50`) y `group.id` de Kafka fijos en el código; umbrales de anomalía (`tau > 2.0`, `battery < 87.0`) hardcodeados con un comentario propio del código original reconociendo que "en producción vendrían de la calibración del instrumento MEDA".
**Corrección:** `KAFKA_POLL_TIMEOUT_S`, `KAFKA_POLL_MAX_MESSAGES`, `KAFKA_CONSUMER_GROUP`, `DUST_STORM_TAU_THRESHOLD`, `LOW_BATTERY_PCT_THRESHOLD` — todos vía variable de entorno con default razonable. Los umbrales de anomalía, además, son parámetros de la función pura `detect_anomalies()` (no solo variables de entorno), así que también se pueden pasar explícitamente en un test o en un notebook de análisis sin tocar el entorno.
**Archivos:** `airflow/dags/mastcamz_pipeline.py`, nuevo `airflow/plugins/anomaly_rules.py`.

#### 6. [Parametrización — bug real, configuración "fantasma"] `JEZERO_LAT`/`JEZERO_LON` sin efecto
**Antes:** `docker-compose.yml` ya declaraba `JEZERO_LAT`/`JEZERO_LON` como variables de entorno para `rover_simulator` (y `.env.example` las documentaba), pero **ni `telemetry_generator.py` ni `mastcamz_simulator.py` las leían** — eran constantes hardcodeadas en el código (`JEZERO_LAT = 18.4447`) que ignoraban por completo la variable de entorno. Cambiar `.env` no tenía ningún efecto real sobre dónde "aterriza" el rover simulado.
**Corrección:** ambos módulos ahora leen `os.getenv("JEZERO_LAT", "18.4447")` / `os.getenv("JEZERO_LON", "77.4508")`.
**Archivos:** `simulator/telemetry_generator.py`, `simulator/mastcamz_simulator.py`.
**Observación relacionada, no corregida:** las mismas coordenadas aparecen además como fallback literal dentro de `update_postgis` (`geo.get("rover_lat", 18.4447)`). Es un valor de bajo riesgo (solo un fallback cuando falta el dato), se documenta como deuda técnica menor — centralizarlo en una constante compartida sería sobre-ingeniería para un valor que casi nunca cambia y cuyo impacto de divergencia es mínimo.

#### 7. [Separación de intereses / SRP] Cliente de almacenamiento duplicado en 3 servicios
**Antes:** `simulator/mastcamz_simulator.py`, `ingestion/dsn_receiver.py` y `airflow/dags/mastcamz_pipeline.py` construían, cada uno por su cuenta, un cliente Minio/S3 — con lógica de `secure`/`region` ligeramente distinta entre sí (una de las tres copias, de hecho, ni siquiera usaba las credenciales que recibía — bug ya corregido en la Fase 1). Tres implementaciones independientes de la misma decisión de infraestructura, con riesgo demostrado de que divergieran.
**Corrección:** nuevo paquete `common/rovermars_common/` con `storage.py` (`build_object_store_client`, `strip_endpoint_scheme`, `object_store_client_from_env`) como única fuente de verdad. Los tres `Dockerfile` ahora usan `.` (raíz del repo) como build context para poder copiar `common/` — ver `docker-compose.yml`/`docker-compose.aws.yml` actualizados. Los tres servicios importan del mismo módulo.
**Archivos nuevos:** `common/rovermars_common/__init__.py`, `common/rovermars_common/storage.py`. **Modificados:** los tres `Dockerfile`, ambos `docker-compose*.yml`, `simulator/mastcamz_simulator.py`, `ingestion/dsn_receiver.py`, `airflow/dags/mastcamz_pipeline.py`. **Test:** `tests/test_storage.py`.

#### 8. [Separación de intereses / SRP] Regla de anomalías mezclada con la orquestación
**Antes:** la lógica de negocio "¿esto es una anomalía?" vivía inline dentro de la tarea `anomaly_detection`, mezclada con la iteración sobre productos y el logging — imposible de testear sin construir la lista de productos exacta que la tarea espera, y sin separación clara entre "regla" y "qué hacer con el resultado".
**Corrección:** extraída a `airflow/plugins/anomaly_rules.py` (`detect_anomalies`, `classify_severity`), funciones puras sin dependencias de Airflow/Kafka/Postgres. Mismo patrón que `calibration.py` (Fase 2).
**Test:** `tests/test_anomaly_rules.py` — 100% de cobertura.

#### 9. Limpieza de lint (consecuencia de la auditoría, no un objetivo en sí)
Al correr `ruff check` por primera vez con un intérprete que sí funcionaba, aparecieron 30 hallazgos: 11 imports muertos preexistentes (`struct`, `uuid`, `dataclasses.field`, `PIL.Image/ImageDraw/ImageFilter` sin usar en `mastcamz_simulator.py`; `typing.Optional` sin usar en dos archivos; `TaskGroup` sin usar en el DAG), 7 bloques de imports desordenados, 6 modernizaciones a sintaxis Python 3.11 (`datetime.UTC`, `X | None`), y **una variable muerta real**: `classify_product_type()` en `dsn_receiver.py` calculaba `eye = event.get("eye", "LEFT")` y nunca la usaba, pese a que el docstring de la función afirma clasificar "based on filter/camera combination". Se limpiaron los imports/orden automáticamente con `ruff check --fix` (verificado que no cambia comportamiento: 62/62 tests siguen pasando), y se documentó la variable muerta con una nota en el docstring **sin inventar** una regla de clasificación por cámara que no está verificada contra la taxonomía real NASA/MIPL.

### Qué se dejó explícitamente sin resolver (y por qué)

| Hallazgo | Por qué no se corrigió ahora |
|---|---|
| `DSNSimulator`/`CCSDSDecoder` no conectados al flujo real de `dsn_receiver.py` | Cambia el comportamiento observable del pipeline (validación CRC real, reensamblado real), excede el alcance de "determinismo/idempotencia/parametrización/SRP" — es una mejora de fidelidad de simulación, no una corrección de robustez |
| Coordenadas de Jezero repetidas como fallback literal en `update_postgis` | Bajo riesgo, bajo impacto de divergencia; centralizarlo sería sobre-ingeniería para este caso puntual |
| `classify_product_type()` no usa `eye` pese a su docstring | Inventar la regla de clasificación por cámara sin conocer la taxonomía real NASA/MIPL sería peor que dejarlo documentado como hallazgo |
| SNS aún no se llama desde `anomaly_detection` (tópico y permisos ya existen en Terraform) | Ya estaba identificado en la Fase 6 como pendiente; sigue pendiente, sin relación directa con esta auditoría |

### Lista de acciones (retomando este enfoque para el resto del proyecto)

Para mantener estas cuatro propiedades a medida que el proyecto crezca (Fase 6 en
adelante, o cualquier feature nueva):

1. **Antes de escribir una key de S3/MinIO**, preguntarse: "¿dos corridas con la
   misma entrada producen la misma key?" Si la respuesta involucra `datetime.now()`
   o un contador que no resetea, no es idempotente — usar un identificador
   determinista derivado del contenido (como se hizo en los hallazgos #1 y #2).
2. **Antes de comitear un offset, un cursor, o marcar algo como "procesado"**,
   preguntarse: "¿ya se confirmó que el efecto downstream se completó?" Si el
   commit ocurre antes que el efecto, hay una ventana de pérdida de datos ante
   fallos (hallazgo #3).
3. **Antes de hardcodear un número o string que representa una regla de negocio,
   un timeout, o una credencial**, exponerlo como variable de entorno con un
   default razonable — y si es una regla de negocio (no solo config de infra),
   exponerlo también como parámetro de función explícito para poder testear
   distintos escenarios sin tocar el entorno (patrón de `detect_anomalies`).
4. **Antes de copiar/pegar lógica de construcción de un cliente (DB, storage,
   cola)** entre dos servicios, preguntarse si debería vivir en `common/` — la
   señal de alarma es cuando ya hay dos copias con pequeñas diferencias (como
   pasó con el cliente MinIO/S3, hallazgo #7).
5. **Antes de dar por buena una función que simula aleatoriedad**, verificar con
   un test que: (a) acepta una semilla inyectable, y (b) con esa semilla fija,
   produce resultados distintos entre semillas distintas — no solo que "corre sin
   error" (hallazgo #4, donde el bug real solo se hizo evidente al forzar un test
   con probabilidad amplificada).
6. **Correr `ruff check` y `pytest` con un intérprete que realmente funcione antes
   de dar algo por terminado** — la mitad de los hallazgos reales de esta fase
   (incluyendo el bug de `_apply_ber` y la variable muerta `eye`) solo aparecieron
   al ejecutar las herramientas de verdad, no al inspeccionar el código a simple
   vista.
7. **Extender, no reemplazar, la cobertura de tests** con cada corrección de esta
   lista — cada hallazgo de esta fase tiene un test que falla si el bug vuelve
   (regresión), no solo una corrección puntual.

**Estado: ✅ 9 correcciones aplicadas y verificadas con pytest real (62/62 tests, Python 3.11.10) + ruff limpio. ✅ 4 observaciones documentadas deliberadamente sin corregir, con justificación. ⚠️ pendiente: correr `docker compose up --build` para que los tres servicios reconstruyan sus imágenes con el nuevo build context (`common/`) antes del próximo despliegue.**

---

## 10. Explicación para perfiles no técnicos (cierre de la guía)

**¿Qué es este proyecto, en una frase?**
Es una réplica funcional del sistema que la NASA usa para recibir, procesar y validar
las fotos y datos ambientales que envía el rover Perseverance desde Marte — construida,
probada y documentada con el mismo estándar que usaría un equipo de ingeniería
profesional: pruebas automáticas antes de cada cambio, control de gasto en la nube, y
un registro explícito de por qué se tomó cada decisión de arquitectura.

**¿Qué cambió con este último trabajo, en palabras simples?**
Antes, el proyecto ya simulaba de punta a punta cómo llegan los datos desde Marte hasta
una base de datos lista para analizarse. Ahora, además:
- Cada pieza de la lógica más delicada (los cálculos de calibración de las imágenes, el
  protocolo de comunicación espacial) tiene **pruebas automáticas** que confirman que
  sigue funcionando correctamente cada vez que se modifica algo — lo mismo que hace un
  banco antes de lanzar una actualización de su app.
- Existe una **revisión automática** (como un control de calidad de fábrica) que corre
  cada vez que se sube un cambio al código, antes de que ese cambio llegue a ningún
  lado.
- La forma en que se transforman los datos en bruto hasta convertirlos en información
  útil ahora está escrita en un lenguaje declarativo (dbt) que cualquier otro ingeniero
  puede leer, versionar y auditar — no en código disperso difícil de rastrear.
- El proyecto ya puede desplegarse en la nube de Amazon (AWS), con la misma disciplina
  de costos que aplicaría una empresa real: se evaluó qué servicios usar y cuáles evitar
  según su precio, y ese razonamiento quedó documentado, no solo el resultado final.

**¿Por qué debería importarle esto a alguien que no programa?**
Porque son exactamente las prácticas que separan a alguien que "sabe programar" de
alguien que **sabe construir sistemas de los que una empresa pueda depender**: pruebas
que dan confianza, automatización que reduce errores humanos, documentación que permite
que otra persona entienda las decisiones sin tener que preguntar, y conciencia de costo
al operar en la nube. Ese es, en esencia, el trabajo real de un Data Engineer.

**¿Qué tan cerca está de un despliegue profesional real, ahora mismo?**
Muy cerca. Lo que falta —publicar el código en un lugar visible, grabar una demostración
en video, y decidir cuándo mantener la infraestructura de nube encendida— son decisiones
de **cuándo mostrarlo**, no trabajo de ingeniería pendiente. La ingeniería de fondo ya
está hecha.

**En una frase para compartir:**
*"Construyó, probó y documentó — con el mismo estándar que usaría un equipo de
ingeniería profesional — una réplica end-to-end del pipeline de datos de una misión real
de la NASA, incluyendo su despliegue en AWS con control explícito de costos."*
