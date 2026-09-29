# Research — Pipeline de Telemetría MEDA

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29

---

## 1. APID Mapping MEDA

**Pregunta**: ¿Cuáles APIDs se usan para cada tipo de sensor MEDA dentro del rango 0x0C0–0x0CF?

**Decisión**:

| Sensor | Descripción | APID (hex) | APID (dec) |
|--------|-------------|------------|------------|
| ATS    | Air Temperature Sensor (boom 1 + 2) | 0x0C0 | 192 |
| PS     | Pressure Sensor | 0x0C1 | 193 |
| WS     | Wind Sensor (TWINS) | 0x0C2 | 194 |
| UV     | UV Irradiance Sensor | 0x0C3 | 195 |
| HS     | Humidity Sensor (TEET) | 0x0C4 | 196 |

**Rationale**: El rango 0x0C0–0x0CF está asignado a MEDA en la tabla APID del proyecto. Se asigna un APID por tipo de sensor, en orden de los cinco subsensores documentados en Sebastián et al. 2021 (Tabla 1). Los APIDs 0x0C5–0x0CF quedan reservados para futuros canales MEDA (infrarrojos, RDS) sin impacto en este pipeline.

**Nota sobre ccsds_encoder.py existente**: El archivo usa 0x01A7 como "MEDA telemetry" — este es un placeholder de la fase Mastcam-Z, previo a la asignación formal del rango MEDA. El simulador MEDA nuevo usará el rango correcto 0x0C0–0x0C4 sin modificar `ccsds_encoder.py` (que queda inalterado para no afectar los tests Mastcam-Z).

**Alternativas consideradas**: Usar un solo APID (0x0C0) con un campo interno de sensor_type — descartado porque el spec establece explícitamente "un paquete por sensor" con "cada APID = un tipo de sensor".

---

## 2. CCSDS Secondary Header — Formato MEDA

**Pregunta**: ¿Qué campos lleva el secondary header de los paquetes MEDA, dado que no tienen `filter_wavelength_nm` como Mastcam-Z?

**Decisión**: Mantener el secondary header en 16 bytes (misma longitud que Mastcam-Z) reemplazando `filter_wavelength_nm` (2 bytes, uint16) por `sensor_type_id` (2 bytes, uint16):

```
Secondary Header MEDA (16 bytes):
  SCLK            — 8 bytes, float64 (Spacecraft Clock, segundos)
  SOL             — 4 bytes, uint32
  SENSOR_TYPE_ID  — 2 bytes, uint16  (1=ATS, 2=PS, 3=WS, 4=UV, 5=HS)
  CRC-16/CCITT    — 2 bytes, uint16
```

**Rationale**: Mantener la longitud idéntica permite reutilizar el decoder existente con un parámetro adicional. El APID ya identifica unívocamente el sensor, pero el campo `sensor_type_id` lo hace explícito en el payload para facilitar el parsing sin consultar la tabla de APIDs.

**Alternativas consideradas**: Usar el APID como único identificador de sensor (sin campo adicional) — descartado porque haría el payload opaco si se reciben paquetes de un APID desconocido fuera del rango esperado.

---

## 3. Ecuaciones de Calibración MEDA

**Fuente primaria**: Sebastián, E. et al. (2021), "The Mars Environmental Dynamics Analyzer, MEDA. A suite of environmental sensors for the Mars 2020 mission", *Journal of Geophysical Research: Planets*, 126, e2021JE006823. DOI: 10.1029/2021JE006823.

**Decisión — Ecuaciones adoptadas para la simulación** (simplificaciones declaradas):

### ATS — Air Temperature Sensor

```
T_c = DN × GAIN_ATS + OFFSET_ATS
```

- `GAIN_ATS = 0.05` °C/DN  
- `OFFSET_ATS = -120.0` °C  
- Rango DN: 0–4095 → Rango T: −120 °C a +84.75 °C  
- Rango operativo documentado en ICD: −120 °C a +40 °C  
- Tolerancia de redondeo: ±0.025 °C (media del paso de cuantización), dentro de la tolerancia de ±0.1 °C del escenario de aceptación 1 de Silver  

**Simplificación declarada**: Los coeficientes reales del modelo de vuelo de MEDA son polinomiales y varían por boom (ATS1/ATS2). Esta implementación usa una conversión lineal única con coeficientes representativos del rango de operación típico en Jezero Crater.

### PS — Pressure Sensor

```
P_hpa = DN × GAIN_PS
```

- `GAIN_PS = 0.0293` hPa/DN  (= 2.93 Pa/DN)
- Rango DN: 0–4095 → Rango P: 0–120.0 hPa (0–1200 Pa)  
- Rango operativo documentado en ICD: 0–1200 Pa ✓  

**Simplificación declarada**: El sensor PS real usa un polinomio de calibración de segundo orden con compensación de temperatura. Esta implementación adopta la aproximación lineal válida para el rango operativo central.

### WS — Wind Sensor (TWINS)

```
wind_speed_ms  = DN_speed × GAIN_WS_SPEED   (m/s)
wind_dir_deg   = DN_dir   × GAIN_WS_DIR     (°)
```

- `GAIN_WS_SPEED = 0.0244` m/s/DN → rango: 0–100 m/s  
- `GAIN_WS_DIR   = 0.0879` °/DN → rango: 0–360°  
- Umbral de tormenta de polvo: `wind_speed_ms ≥ 20.0 m/s` (configurable vía `MEDA_DUST_STORM_WIND_THRESHOLD`)  

**Simplificación declarada**: TWINS usa un array de sensores de película caliente; la calibración real depende de la dirección del viento y la densidad del flujo. Esta implementación usa conversiones lineales independientes.

### UV — UV Irradiance Sensor

```
uv_irr_w_m2 = DN × GAIN_UV
```

- `GAIN_UV = 0.00244` W/m²/DN → rango: 0–10 W/m²  

**Simplificación declarada**: El sensor UV real tiene seis fotodiodos con diferentes filtros espectrales. Esta implementación agrega en una irradiancia total.

### HS — Humidity Sensor (TEET)

```
humidity_pct = DN × GAIN_HS
```

- `GAIN_HS = 0.0244` %/DN → rango: 0–100%  

**Simplificación declarada**: El sensor real usa corrección de temperatura y humedad relativa. Esta implementación usa conversión lineal representativa.

---

## 4. Rangos Físicos Operativos y Umbrales de Anomalía

**Fuente**: Sebastián et al. 2021 (Tabla 2 — MEDA Science Requirements); ICD de MEDA.

| Sensor | Rango válido Silver | Umbral anomalía | Variable de entorno |
|--------|-------------------|-----------------|---------------------|
| ATS — temperatura | −120 °C a +40 °C | < −120 o > +40 | `MEDA_TEMP_MIN_C`, `MEDA_TEMP_MAX_C` |
| PS — presión | 0 hPa a 120 hPa (0–1200 Pa) | < 0 o > 120 | `MEDA_PRESSURE_MIN_HPA`, `MEDA_PRESSURE_MAX_HPA` |
| WS — velocidad | 0 m/s a 100 m/s | > 20 m/s (tormenta de polvo) | `MEDA_DUST_STORM_WIND_THRESHOLD` |
| UV — irradiancia | 0 W/m² a 10 W/m² | < 0 o > 10 | `MEDA_UV_MIN_W_M2`, `MEDA_UV_MAX_W_M2` |
| HS — humedad | 0 % a 100 % | < 0 o > 100 | `MEDA_HUM_MIN_PCT`, `MEDA_HUM_MAX_PCT` |

Defaults codificados en `meda_anomaly_rules.py` con lectura vía `os.getenv()`, siguiendo el patrón de `anomaly_rules.py`.

---

## 5. Perfil Diurno de Temperatura (Simulador)

**Pregunta**: ¿Cómo modelar el patrón circadiano de temperatura marciana para satisfacer el Escenario 4?

**Decisión**:

```python
# LMST en horas decimales (0.0–24.659 para un sol marciano)
T(lmst_h) = T_MEAN + A × sin(2π × (lmst_h - T_PEAK_LMST) / SOL_DURATION_H - π/2)
```

- `T_MEAN = -60.0` °C  
- `A = 30.0` °C (amplitud media diurna en Jezero Crater, basada en datos publicados de MEDA)  
- `T_PEAK_LMST = 14.0` h (máximo post-mediodía, entre 13:00–15:00 LMST) ✓  
- `SOL_DURATION_H = 24.659` h (duración real del sol marciano) ✓  
- Mínimo en `t_min ≈ T_PEAK_LMST - SOL_DURATION_H/2 ≈ 1.67 h LMST` (entre 02:00–06:00) ✓  

**Rationale**: El modelo sinusoidal reproduce el patrón cualitativo de MEDA documentado en Sullivan et al. 2023 (GRL) con mínimo pre-amanecer y máximo post-mediodía, suficiente para la verificación del escenario 4 (CE con hash SHA-256 y rangos de horario).

**Referencia**: Datos de temperatura MEDA en Jezero Crater disponibles en NASA PDS (bundle `urn:nasa:pds:mars2020_meda`) muestran amplitudes diurnas de 25–40 °C con perfil asimétrico (calentamiento rápido, enfriamiento lento); el modelo sinusoidal es la simplificación mínima que cumple los criterios de aceptación.

---

## 6. Diseño del DAG MEDA — Decisiones de Orquestación

**Pregunta**: ¿Hay diferencias estructurales entre el DAG MEDA y el DAG Mastcam-Z que requieran un diseño diferente?

**Decisión**: El DAG MEDA sigue el mismo patrón de 10 tareas y el mismo wiring de dependencias:

```
poll_meda_queue → ingest_raw → validate_bronze → calibrate_silver
  → write_silver_minio → update_silver_postgres → detect_anomalies
  → build_gold_aggregates → dbt_build
  → commit_kafka_offsets → notify
```

**Diferencias respecto a Mastcam-Z**:
1. Topic Kafka: `telemetry.meda.raw` (nuevo, independiente de `etl.bronze.ready`)
2. No hay tarea de calibración geométrica (MEDA es telemetría ambiental, no imagen)
3. `ingest_raw` escribe directamente a MinIO con clave determinista — MEDA no tiene capa PDS4 XML
4. `validate_bronze` valida CRC, APID range, payload size, campos obligatorios → upsert en `meda_bronze_records`
5. `calibrate_silver` consolida múltiples registros Bronze del mismo `(sol, sclk)` en una sola fila Silver con todos los sensores disponibles
6. Buckets: `meda-raw`, `meda-bronze`, `meda-silver`, `meda-gold`

**Alternativas consideradas**: DAG con fanout por tipo de sensor (5 ramas paralelas) — descartado porque la consolidación de sensores por `(sol, sclk)` en Silver requiere que todos los sensores del mismo instante estén disponibles antes de escribir; el fan-in añade complejidad sin beneficio de rendimiento para lotes de 100 paquetes.

---

## 7. Postgres — Nuevas Tablas MEDA

**Pregunta**: ¿Las tablas MEDA deben estar en el mismo schema que `image_products` o en un schema separado?

**Decisión**: Las tablas `meda_bronze_records` y `meda_silver_readings` van en el schema `raw` y `science` respectivamente (alineadas con la convención del `schema.sql` existente — `raw` para Bronze, `science` para Silver).

| Tabla | Schema | Rol |
|-------|--------|-----|
| `meda_bronze_records` | `raw` | Metadatos de validación, un registro por paquete CCSDS |
| `meda_silver_readings` | `science` | Lecturas calibradas consolidadas, una fila por `(sol, sclk)` |

**Rationale**: Separar MEDA en sus propias tablas (sin extender `image_products`) preserva el aislamiento de tests Mastcam-Z (Principio III) y hace el modelo más claro para un analista: una tabla de imágenes no debería contener lecturas de temperatura.
