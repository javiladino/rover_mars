# Especificación de Feature: Pipeline de Telemetría MEDA

**Feature Branch**: `001-meda-pipeline`

**Creado**: 2026-09-28

**Estado**: Borrador

**Versión**: 0.1.0

**Constitución aplicada**: v1.0.0

---

## Escenarios de Usuario y Prueba *(obligatorio)*

### Escenario 1 — Ingestión y validación de lecturas ambientales (Prioridad: P1)

El equipo de datos puede publicar un lote de paquetes CCSDS de MEDA (temperatura,
presión, viento, UV, humedad) hacia Kafka y ver esos registros aterrizados en la
capa Raw (MinIO) y catalogados en Bronze (Postgres) sin pérdida ni mutación del
payload original.

**Por qué esta prioridad**: Es la base del pipeline. Sin ingestión validada no hay
capas Silver ni Gold. Entrega valor inmediato: prueba que la arquitectura soporta un
segundo subsistema de datos.

**Prueba independiente**: Lanzar el simulador MEDA, consumir el topic Kafka y verificar
que el objeto Raw en MinIO existe con contenido idéntico al payload original y que la
tabla Bronze en Postgres contiene el registro con `crc_valid = true`.

**Escenarios de aceptación**:

1. **Dado** un paquete CCSDS de MEDA con CRC válido en el topic `telemetry.meda.raw`,
   **Cuando** el DAG ejecuta la tarea de ingestión,
   **Entonces** el objeto aparece en `meda-raw/{sol}/{apid}/{packet_id}.bin` en MinIO
   y el registro en la tabla Bronze tiene `schema_valid = true`, `crc_valid = true`.

2. **Dado** un paquete CCSDS con CRC corrupto,
   **Cuando** el DAG ejecuta la tarea de validación,
   **Entonces** el registro Bronze se persiste con `crc_valid = false` y
   `quarantine_reason = 'crc_mismatch'`; el pipeline no propaga el registro a Silver.

3. **Dado** un reintento del DAG sobre el mismo lote,
   **Cuando** el objeto Raw ya existe en MinIO,
   **Entonces** el objeto no se sobrescribe (Raw inmutable) y el registro Bronze se
   actualiza por upsert sin duplicados.

---

### Escenario 2 — Calibración física a unidades SI (Prioridad: P1)

El equipo de ciencia puede consultar lecturas MEDA en unidades físicas calibradas
(°C, hPa, m/s, W/m², %) en Silver, derivadas a partir de los valores crudos en DN
aplicando los factores de conversión documentados en la literatura MEDA.

**Por qué esta prioridad**: Los datos crudos (DN o cuentas ADC) no tienen valor
analítico sin calibración. Silver es la capa de consumo científico.

**Prueba independiente**: Dado un conjunto de lecturas Bronze sintéticas con valores DN
conocidos, la función de calibración pura retorna los valores físicos esperados dentro
de la tolerancia de la especificación del instrumento (± 1 °C en temperatura,
± 0.5 hPa en presión).

**Escenarios de aceptación**:

1. **Dado** una lectura Bronze de temperatura ATS con valor DN conocido,
   **Cuando** se aplica la función de calibración,
   **Entonces** el valor Silver en °C coincide con la conversión documentada
   (referencia: Sebastián et al. 2021, J. Geophysical Research, ecuación de calibración
   de ATS) dentro de ± 0.1 °C de tolerancia de redondeo.

2. **Dado** una lectura de presión PS con valor fuera del rango operativo de MEDA
   (0–1200 Pa según ICD),
   **Cuando** se ejecuta la validación de rango Silver,
   **Entonces** el registro se persiste en Silver con `anomaly_flag = true` y
   `anomaly_reason = 'pressure_out_of_range'`.

3. **Dado** el mismo lote de lecturas Bronze ejecutado dos veces,
   **Cuando** se persiste en Silver y Postgres con upsert,
   **Entonces** el sistema queda en el mismo estado (idempotencia verificada por
   conteo de filas y valores en Silver).

---

### Escenario 3 — Agregados Gold y modelos dbt para análisis por sol (Prioridad: P2)

Un analista puede consultar estadísticas ambientales diarias de Marte (temperatura
mínima/media/máxima por sol, presión media, velocidad máxima de viento, dosis UV
acumulada) desde los modelos dbt marts, sin necesidad de procesar datos crudos.

**Por qué esta prioridad**: Es la capa de consumo final (BI, Grafana, notebooks). Sin
ella el pipeline no cierra el ciclo analítico, pero puede demostrarse antes de que
Gold esté completo.

**Prueba independiente**: Ejecutar `dbt build` sobre datos Silver sintéticos en Postgres
y verificar que `fct_meda_sol_summary` devuelve una fila por sol con los campos
agregados correctos y que los tests declarativos (`not_null`, `unique`, rangos físicos)
pasan en verde.

**Escenarios de aceptación**:

1. **Dado** un conjunto de lecturas Silver para el sol 100,
   **Cuando** se ejecuta `dbt build`,
   **Entonces** `fct_meda_sol_summary` contiene exactamente una fila para sol=100
   con `temp_min_c`, `temp_max_c`, `temp_avg_c`, `pressure_avg_hpa`,
   `wind_speed_max_ms`, `uv_dose_wh_m2` no nulos y dentro de rangos físicos válidos.

2. **Dado** que el DAG de Airflow ya corrió `build_gold_aggregates`,
   **Cuando** se ejecuta `dbt build` sobre los mismos datos,
   **Entonces** los modelos dbt no duplican la agregación sino que operan sobre
   la capa Silver de Postgres (ADR-001: coexistencia declarada, no duplicación
   accidental).

---

### Escenario 4 — Simulador MEDA como fuente de datos de prueba (Prioridad: P2)

El equipo de ingeniería puede ejecutar el simulador MEDA en local para generar
telemetría sintética realista (con patrones circadianos de temperatura y presión
coherentes con datos reales de Perseverance) y publicarla en Kafka, sin necesidad
de acceso a datos reales de la NASA.

**Por qué esta prioridad**: El simulador es el único origen de datos disponible en
desarrollo local. Sin él, los demás escenarios no son probables en CI.

**Prueba independiente**: Ejecutar `meda_simulator.py` con semilla fija y verificar
que el output de Kafka es determinista (misma secuencia de paquetes CCSDS para la
misma semilla) y que los valores de temperatura siguen el patrón diurno esperado
(mínimo pre-amanecer, máximo post-mediodía marciano).

**Escenarios de aceptación**:

1. **Dado** el simulador iniciado con `--seed 42 --sols 1`,
   **Cuando** se generan los paquetes y se publican en Kafka,
   **Entonces** la secuencia de paquetes es idéntica en dos ejecuciones consecutivas
   con la misma semilla (determinismo verificado por hash SHA-256 del payload
   concatenado).

2. **Dado** un sol simulado de 24:39:35 (duración real del sol marciano),
   **Cuando** se grafican los valores de temperatura ATS a lo largo del sol,
   **Entonces** el perfil muestra un mínimo entre las 02:00–06:00 LMST y un máximo
   entre las 13:00–15:00 LMST, coherente con datos de MEDA publicados por NASA/JPL.

---

### Casos Límite

- ¿Qué ocurre si el topic Kafka `telemetry.meda.raw` no existe cuando el DAG
  arranca? → El DAG falla con error descriptivo; no se crean objetos Raw parciales.
- ¿Qué ocurre si un paquete MEDA llega con APID desconocido (fuera del rango
  0x0C0–0x0CF asignado a MEDA en la tabla APID del proyecto)? → Se descarta con
  registro en Bronze bajo `quarantine_reason = 'unknown_apid'`.
- ¿Qué pasa si la tabla Silver de Postgres no tiene el registro Bronze correspondiente
  al intentar la calibración? → La tarea lanza una excepción gestionada y el DAG
  reintenta según la política de `retries = 2`.
- ¿Qué ocurre si el simulador recibe un rango de sol fuera de [0, 999]? → El
  simulador rechaza el argumento con un `ValueError` descriptivo antes de generar
  ningún paquete.
- ¿Qué pasa si el modelo dbt detecta una fila Silver con `sol = NULL`? → El test
  `not_null` de dbt falla y el `dbt build` se aborta con salida no-cero, lo que
  hace fallar la tarea `dbt_build` del DAG.

---

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **RF-001**: El sistema DEBE simular paquetes de telemetría MEDA (temperatura ATS,
  presión PS, viento WS, UV, humedad HS) encapsulados en CCSDS con APIDSs del
  rango asignado a MEDA, con valores físicos sintéticos coherentes con los rangos
  operativos del instrumento real (Sebastián et al. 2021).

- **RF-002**: El sistema DEBE publicar los paquetes MEDA en un topic Kafka dedicado
  (`telemetry.meda.raw`) independiente del topic Mastcam-Z, para permitir que ambos
  pipelines escalen y fallen de forma aislada.

- **RF-003**: El DAG DEBE almacenar cada paquete MEDA recibido en Raw (MinIO) con una
  clave determinista basada en `(sol, apid, packet_id)`, sin sufijos de timestamp
  variables, garantizando que re-ejecuciones no generen objetos duplicados.

- **RF-004**: El DAG DEBE validar en Bronze que cada paquete tiene CRC correcto,
  APID dentro del rango MEDA, tamaño de payload dentro del límite CCSDS, y campos
  obligatorios presentes; registros que fallen cualquier validación se marcan en
  cuarentena sin propagarse a Silver.

- **RF-005**: El DAG DEBE calibrar en Silver los valores DN a unidades físicas SI
  aplicando las ecuaciones de conversión de MEDA documentadas, separando la lógica
  matemática pura en `airflow/plugins/meda_calibration.py` (sin dependencias de
  Airflow, Kafka ni Postgres).

- **RF-006**: El DAG DEBE persistir las lecturas Silver en Postgres con upsert
  `ON CONFLICT DO UPDATE`, incluida la posición geoespacial del rover al momento de
  la lectura (PostGIS), de modo que re-ejecuciones no dupliquen filas.

- **RF-007**: El DAG DEBE detectar anomalías MEDA (temperatura fuera de rango,
  viento sobre umbral de tormenta de polvo, presión anómala) usando un nuevo
  módulo `meda_anomaly_rules.py` independiente, siguiendo el mismo patrón de
  función pura que `anomaly_rules.py` pero sin modificar ni extender ese módulo,
  preservando el aislamiento de tests Mastcam-Z (Principio III).

- **RF-008**: Los modelos dbt DEBEN agregarse a nivel de sol en `fct_meda_sol_summary`
  (temperatura min/media/max, presión media, velocidad máxima de viento, dosis UV
  acumulada) con tests declarativos que validen rangos físicos.

- **RF-009**: El DAG DEBE diferir el commit de offsets Kafka hasta confirmar que los
  writes a Silver, Postgres y Gold han sido exitosos, siguiendo el patrón
  `commit_kafka_offsets` ya establecido.

- **RF-010**: El simulador MEDA DEBE aceptar una semilla aleatoria (`--seed`) que
  garantice determinismo total del output, permitiendo reproducción exacta en tests.

### Entidades Clave

- **Lectura MEDA Cruda (Raw)**: paquete CCSDS binario con APID MEDA, `sol`,
  `sclk` (Spacecraft Clock), payload de UN sensor. Inmutable una vez escrito.
  Cada tipo de sensor tiene su propio APID dentro del rango 0x0C0–0x0CF.

- **Registro MEDA Bronze**: metadatos de validación de un paquete Raw (uno por
  paquete de sensor): `packet_id`, `sol`, `sclk`, `apid`, `sensor_type`
  (ATS | PS | WS | UV | HS), `crc_valid`, `schema_valid`,
  `quarantine_reason` (nullable), `arrival_utc`.

- **Lectura MEDA Silver**: consolidación calibrada de múltiples registros Bronze
  del mismo `(sol, sclk)` — una fila por instante de muestreo, con todos los
  sensores disponibles: `sol`, `sclk`, `lmst` (Local Mean Solar Time),
  `temperature_ats_c`, `pressure_hpa`, `wind_speed_ms`, `wind_direction_deg`,
  `uv_irradiance_w_m2`, `humidity_pct`, `anomaly_flag`, `anomaly_reason`,
  `rover_lon`, `rover_lat` (PostGIS point). Campos de sensores ausentes en ese
  instante se persisten como NULL con un flag de cobertura.

- **Resumen Sol MEDA Gold** (`fct_meda_sol_summary`): agregados diarios por sol:
  `sol`, `temp_min_c`, `temp_max_c`, `temp_avg_c`, `pressure_avg_hpa`,
  `wind_speed_max_ms`, `uv_dose_wh_m2`, `reading_count`, `anomaly_count`.

- **Dimensión Estación DSN**: reutilizada de `dim_dsn_stations` existente; las
  lecturas MEDA se reciben por el mismo enlace DSN que Mastcam-Z.

---

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **CE-001**: Un lote de 100 lecturas MEDA sintéticas fluye de extremo a extremo
  (simulador → Kafka → Raw → Bronze → Silver → Gold → dbt) en menos de 5 minutos
  en el entorno local con `docker compose up`.

- **CE-002**: Re-ejecutar el mismo lote dos veces produce exactamente el mismo
  estado final en MinIO y Postgres (cero registros duplicados, cero objetos Raw
  adicionales), verificable por conteo de filas y hash de objetos.

- **CE-003**: La suite de tests del módulo `meda_calibration.py` cubre el 100% de
  las funciones de calibración con al menos un caso por sensor, y todos pasan en
  verde bajo Python 3.11 sin infraestructura real.

- **CE-004**: `dbt build` sobre datos Silver sintéticos termina en verde con todos
  los tests declarativos pasando, incluyendo unicidad de `(sol, packet_id)` y
  rangos físicos válidos en `fct_meda_sol_summary`.

- **CE-005**: `ruff check` sobre todos los archivos nuevos retorna cero hallazgos.

- **CE-006**: Los workflows de CI (`lint.yml`, `test.yml`, `dbt-ci.yml`) pasan en
  verde después de integrar el pipeline MEDA.

- **CE-007**: El diagrama de arquitectura en `README.md` refleja el nuevo subsistema
  MEDA como segundo flujo de datos en el medallion, sin un PR separado posterior.

---

## Suposiciones

- El mecanismo de transporte (CCSDS sobre Kafka) es idéntico al de Mastcam-Z; solo
  cambian los APIDSs y el esquema de payload.
- Los factores de calibración de MEDA se toman de Sebastián et al. 2021 (J. Geophys.
  Res. Planets, 126, e2021JE006823) como referencia primaria; donde el paper no
  provea precisión suficiente se declarará simplificación deliberada en el código.
- Los buckets MinIO `meda-raw`, `meda-bronze`, `meda-silver` se crean en
  `docker-compose.yml` con el mismo patrón que los buckets de Mastcam-Z; no se
  requiere un ADR nuevo para este cambio (misma tecnología, mismo patrón).
- La posición geoespacial del rover al momento de cada lectura MEDA se toma del
  mismo registro de posición ya disponible en Postgres (tabla de trayectoria del
  rover), sin necesidad de un nuevo subsistema de geolocalización.
- El pipeline MEDA coexiste con el pipeline Mastcam-Z en el mismo Airflow; no se
  requiere un segundo worker ni cambios al `docker-compose.yml` de Airflow.
- Los modelos dbt MEDA se agregan al mismo proyecto dbt existente en `dbt/`,
  bajo `models/staging/` y `models/marts/`, siguiendo las convenciones de nombrado
  ya establecidas (`stg_`, `fct_`, `dim_`).
- El DAG MEDA sigue el mismo patrón de 10–11 tareas que `mastcamz_pipeline.py`;
  las diferencias estarán en los módulos de calibración y las reglas de anomalía,
  no en la estructura de orquestación.

---

## Clarifications

### Session 2026-09-29

- Q: ¿El módulo de reglas de anomalía para MEDA debe implementarse extendiendo `anomaly_rules.py` existente o creando un nuevo módulo `meda_anomaly_rules.py` independiente? → A: Nuevo módulo `meda_anomaly_rules.py` independiente
- Q: ¿Cada paquete CCSDS de MEDA contiene lecturas de un solo sensor o de todos los sensores juntos? → A: Un paquete por sensor (cada APID = un tipo de sensor); Silver consolida por (sol, sclk)
