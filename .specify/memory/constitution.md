<!--
SYNC IMPACT REPORT — Constitution Amendment
============================================
Version change    : (initial) → 1.0.0
Modified sections : none (first ratification)
Added sections    :
  - Principios Fundamentales (I–VIII)
  - Restricciones Técnicas y de Presentación
  - Flujo de Trabajo Speckit
  - Gobernanza
Removed sections  : none
Deferred TODOs    : none — all placeholders resolved from user input
Review note       : Remove this comment block before committing to the repo.
============================================
-->

# Constitución del Proyecto — Rover Mars

Este documento gobierna cómo se especifica, planifica e implementa cualquier
trabajo nuevo sobre `rover_mars` bajo el framework Speckit (`/constitution`,
`/specify`, `/plan`, `/tasks`, `/implement`). Toda spec (`/specify`) y todo plan
(`/plan`) generado a partir de aquí debe poder justificar, principio por
principio, por qué cumple con lo escrito abajo — y si no puede, la spec debe
declarar la excepción explícitamente y por qué se justifica (ver Gobernanza).

No es un documento aspiracional: cada principio está anclado en una decisión ya
tomada y verificada en este repositorio (ver referencias a ADRs en
`docs/ANALISIS_MODERN_DATA_STACK.md` y a la auditoría de Fase 7 en
`docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`), no en buenas prácticas
genéricas de manual.

## Principios Fundamentales

### I. Fidelidad de dominio (NO NEGOCIABLE)

Toda simulación, fórmula, formato de datos o comportamiento de protocolo DEBE
ser trazable a documentación técnica real (papers NASA/JPL, estándares CCSDS,
PDS4, especificaciones de instrumento) o estar explícitamente marcado como
simplificación con su razón. El diferenciador central de este proyecto —lo que
lo separa de un ejercicio con datos de Kaggle— es que cada pieza (specs de
Mastcam-Z, CCSDS 133.0-B-2, modelo CAHVOR, formato PDS4, modelo MEDA) responde
a una fuente real y citada. Ninguna feature nueva puede inventar un protocolo,
una fórmula física o un formato de producto "porque suena razonable": si no
hay fuente, se documenta como simplificación deliberada (como ya se hace con
el modelo CAHVOR simplificado o el I/F simplificado en
`airflow/plugins/calibration.py`), nunca se presenta como réplica fiel sin
serlo.

### II. El contrato Medallion es un contrato, no una convención de carpetas

Las capas Raw → Bronze → Silver → Gold DEBEN respetar sus garantías: Raw es
inmutable y nunca se reescribe; Bronze solo valida y cataloga, no transforma
valores; Silver es donde ocurre toda calibración/enriquecimiento; Gold es
agregado y listo para consumo (BI, notebooks, dashboards). Ningún cambio puede
escribir directamente a Gold saltándose Silver, ni mutar un objeto ya escrito
en Raw/Bronze. Cuando una misma responsabilidad de agregación exista en dos
caminos a la vez (hoy: el JSON de Gold en MinIO/S3 escrito por
`build_gold_aggregates` y los modelos `dbt` en `dbt/models/marts/`), ambos
caminos DEBEN quedar documentados como coexistencia deliberada (ver ADR-001),
no como duplicación accidental.

### III. Determinismo, idempotencia, parametrización y responsabilidad única

Toda tarea o función nueva en el pipeline DEBE cumplir las cuatro propiedades
auditadas en la Fase 7 (`docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`):

- **Determinismo**: misma entrada → misma salida (los timestamps de auditoría
  como `generated_at`/`arrival_utc` son la única excepción legítima).
- **Idempotencia**: ejecutar la misma tarea dos veces con la misma entrada deja
  el sistema en el mismo estado final — keys de S3/MinIO deterministas, upserts
  `ON CONFLICT` en Postgres, commits diferidos hasta confirmar éxito downstream
  (patrón establecido en `commit_kafka_offsets`), nunca timestamps en nombres de
  objetos que se supone son "el snapshot actual".
- **Parametrización**: ningún umbral de negocio, timeout, nombre de bucket,
  credencial o coordenada de referencia se hardcodea — se expone vía variable
  de entorno con default razonable y, si es una regla de negocio, también como
  parámetro de función explícito (patrón de `detect_anomalies` en
  `airflow/plugins/anomaly_rules.py`).
- **Responsabilidad única**: la lógica de negocio pura (cálculos, reglas de
  clasificación, bookkeeping) vive separada del I/O de orquestación
  (Kafka/Postgres/S3), en módulos testeables sin infraestructura real
  (`airflow/plugins/calibration.py`, `anomaly_rules.py`, `kafka_offsets.py`,
  `common/rovermars_common/storage.py`). Antes de copiar lógica de
  construcción de un cliente entre dos servicios, se centraliza en `common/`.

### IV. Verificación real antes de declarar algo terminado

Ningún cambio se considera completo por haber sido revisado a simple vista.
DEBE correr `pytest` y `ruff check` realmente (no solo razonamiento manual
sobre el código) contra un intérprete que coincida con el runtime real
(Python 3.11, igual que `python:3.11-slim` y `apache/airflow:2.9.1-python3.11`)
antes de reportarse como hecho. Este principio existe porque ya ocurrió: la
auditoría de Fase 7 encontró errores reales (un bug de truncamiento en
`_apply_ber`, una variable muerta en `classify_product_type`, y un error en un
test propio con un payload que excedía el límite CCSDS) que la revisión manual
no había detectado, y que solo aparecieron al ejecutar las herramientas de
verdad. Toda spec que agregue lógica no trivial DEBE listar en su plan de
verificación qué tests nuevos cubren el comportamiento y qué comando los
ejecuta.

### V. Seguridad de secretos por defecto

Ninguna credencial, clave o token se hardcodea en código ni en
`docker-compose*.yml`. Todo secreto vive en `.env` (excluido de git,
documentado con placeholders en `.env.example`) en local, y en AWS SSM
Parameter Store (`infra/aws/ssm.tf`, ADR-017) en la nube, leído vía rol IAM de
mínimo privilegio. Ningún recurso AWS se expone públicamente sin que la spec
correspondiente justifique por qué (ver ADR-014 sobre por qué Airflow/Kafka
quedan en un EC2 con acceso acotado en vez de gestionados).

### VI. Ingeniería consciente del costo en la nube

Toda decisión de adoptar o descartar un servicio gestionado de AWS DEBE
evaluarse con el mismo criterio que ADR-011 a ADR-020: costo marginal frente a
señal técnica ganada, con el crédito de estudiante como restricción real y no
teórica. Descartar un servicio "enterprise" (como ya se hizo con MWAA y MSK)
es un resultado válido y se documenta con la misma rigurosidad que adoptar
uno. Ningún recurso de pago se provisiona sin que `infra/aws/budgets.tf`
(alertas al 50/80/100%) ya esté aplicado, y todo `terraform apply` que gaste
crédito real requiere revisión de `terraform plan` primero — nunca se aplica
a ciegas.

### VII. Toda decisión de arquitectura no trivial es un ADR

Un cambio de tecnología, un rediseño de un componente, o la elección entre dos
enfoques con trade-offs reales DEBE registrarse como ADR en
`docs/ANALISIS_MODERN_DATA_STACK.md`, siguiendo el formato ya establecido
(Contexto → Decisión → Consecuencias → Alternativas consideradas), antes de o
junto con la implementación. Una spec de Speckit que implique una decisión de
este tipo referencia el ADR correspondiente (nuevo o existente) en vez de
repetir el razonamiento inline.

### VIII. Transformación declarativa y CI como guardián, no como documentación

Lógica de agregación/transformación Silver→Gold nueva se implementa como
modelo `dbt` con tests declarativos (`dbt/models/`), no como Python imperativo
dentro de una tarea de Airflow — Airflow orquesta, dbt transforma (ADR-001).
Ningún cambio se considera mergeable si `.github/workflows/lint.yml`,
`test.yml`, `dbt-ci.yml` o `docker-build.yml` no pasan en verde; los workflows
son la fuente de verdad sobre si el proyecto "funciona", no una aspiración
documental.

## Restricciones Técnicas y de Presentación

- **Stack fijo salvo ADR en contra**: Python 3.11, Apache Airflow 2.9
  (LocalExecutor), PostgreSQL 16 + PostGIS 3.4, Kafka vía imágenes Confluent
  7.6, dbt-core/dbt-postgres 1.8.x, Terraform con `hashicorp/aws ~> 5.0`.
  Cambiar cualquiera de estos requiere un ADR, no un cambio silencioso de
  versión.
- **Contexto de build Docker = raíz del repo**: los tres `Dockerfile`
  (`simulator/`, `ingestion/`, `airflow/`) construyen desde la raíz del repo
  para poder copiar `common/rovermars_common/`. Ningún servicio nuevo
  reintroduce un cliente de almacenamiento o de base de datos propio si ya
  existe una fábrica equivalente en `common/`.
- **Higiene de repositorio**: la raíz del repo se mantiene limpia (solo
  README, LICENSE, `.env.example`, Makefile, docker-compose\*, configs de
  herramientas); material exploratorio va a `docs/drafts/`; nada bajo
  `data/raw|bronze|silver|gold/` se versiona (solo `.gitkeep`); ningún secreto
  real llega a un commit.
- **Idioma de la documentación**: toda la documentación de este proyecto
  (README, ADRs, guía de implementación, comentarios de código nuevo) se
  redacta en español hasta que se ejecute la migración a inglés previa a la
  publicación pública del proyecto. Una spec que agregue documentación no
  mezcla ambos idiomas dentro de un mismo archivo.
- **El dashboard y el README son entregables, no accesorios**: este es un
  proyecto de portafolio pensado para reclutadores técnicos y no técnicos
  (ver sección 10 de la guía de implementación). Un cambio de arquitectura
  visible (nuevo servicio, nuevo flujo de datos) actualiza el diagrama Mermaid
  correspondiente en `README.md`/`dashboard/index.html` en el mismo cambio,
  no como tarea separada "para después".

## Flujo de Trabajo Speckit

1. **`/constitution`** — cambios a este documento siguen el procedimiento de
   Gobernanza más abajo; no se edita este archivo como parte de una spec de
   feature.
2. **`/specify`** — toda spec nueva declara, en una sección de cumplimiento,
   qué principios de este documento aplican y cómo los satisface; si alguno no
   aplica o se viola deliberadamente, la spec lo dice explícitamente y por qué
   (ver Gobernanza § excepciones).
3. **`/plan`** — el plan técnico referencia los ADRs relevantes ya existentes
   o marca la necesidad de uno nuevo (Principio VII), y enumera el stack
   fijado en "Restricciones Técnicas" salvo que justifique desviarse.
4. **`/tasks`** — cada tarea que toque lógica de pipeline incluye su
   contraparte de test (Principio IV) y, si aplica, su actualización de
   diagrama/documentación (Restricciones de Presentación) como parte de la
   misma tarea, no de una tarea de "limpieza" posterior.
5. **`/implement`** — ninguna tarea se marca completa sin haber corrido
   `pytest`/`ruff` realmente (Principio IV); el criterio de aceptación es la
   corrida en verde, no la lectura del diff.

## Gobernanza

- Esta constitución prevalece sobre preferencias de estilo individuales o
  atajos de conveniencia dentro del alcance de `rover_mars`; no prevalece
  sobre instrucciones explícitas del usuario para una tarea puntual, que
  pueden crear una excepción consciente.
- **Excepciones**: una spec o plan puede desviarse de un principio solo si lo
  declara explícitamente con su razón (ej.: "se pospone el test de X porque Y,
  se registra como deuda técnica en la guía de implementación"). Una excepción
  silenciosa no es una excepción válida.
- **Enmiendas**: cambiar un principio, agregar uno nuevo, o eliminar uno
  requiere: (1) justificar el cambio con evidencia del código o de una
  decisión ya tomada (mismo estándar que un ADR), (2) actualizar este archivo,
  (3) incrementar la versión según semver (MAJOR: se elimina o redefine un
  principio de forma incompatible con specs previas; MINOR: se agrega un
  principio o sección nueva; PATCH: aclaración o corrección de redacción sin
  cambio de sentido), y (4) actualizar la fecha de "Última Enmienda" abajo.
- Toda revisión de una spec/plan/PR generada bajo Speckit debe poder señalar,
  para cada principio de la sección "Principios Fundamentales", si se cumple,
  no aplica, o se excepciona explícitamente — no se aprueba trabajo que un
  principio contradiga sin excepción declarada.

**Versión**: 1.0.0 | **Ratificada**: 2026-09-28 | **Última Enmienda**: 2026-09-28
