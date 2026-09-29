# Contrato — Kafka Topic `telemetry.meda.raw`

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29

---

## Identificación del Topic

| Propiedad | Valor |
|-----------|-------|
| Topic name | `telemetry.meda.raw` |
| Bootstrap servers | `kafka:9092` (local) / `${KAFKA_BOOTSTRAP}` (env) |
| Particiones sugeridas | 5 (una por tipo de sensor para localidad de datos) |
| Retention | 7 días (default Confluent) |
| Producer | `simulator/meda_simulator.py` |
| Consumer | `airflow/dags/meda_pipeline.py` (task `poll_meda_queue`) |

**Independencia**: este topic es completamente independiente de `etl.bronze.ready` (Mastcam-Z). Cada pipeline puede escalar, fallar y reintentar de forma aislada (RF-002).

---

## Esquema del Mensaje Kafka

Cada mensaje es un **JSON UTF-8** con los campos siguientes. La clave Kafka (key) es el `packet_id`.

```json
{
  "packet_id":     "a3f2b1c9d4e5f607",
  "sol":           42,
  "sclk":          123456789.5,
  "apid":          192,
  "apid_hex":      "0xC0",
  "sensor_type":   "ATS",
  "payload_b64":   "<base64-encoded CCSDS packet bytes>",
  "crc_computed":  61234,
  "produced_utc":  "2026-09-29T14:32:00.123Z",
  "simulator_seed": 42
}
```

### Descripción de campos

| Campo | Tipo | Obligatorio | Descripción |
|-------|------|-------------|-------------|
| `packet_id` | string (16 hex chars) | ✓ | SHA-256 del payload CCSDS, primeros 16 hex chars; clave determinista para MinIO y Bronze |
| `sol` | integer (0–999) | ✓ | Sol marciano del paquete |
| `sclk` | float | ✓ | Spacecraft Clock en segundos; identifica el instante de muestreo |
| `apid` | integer (192–207) | ✓ | APID decimal (0x0C0–0x0CF) |
| `apid_hex` | string | ✓ | APID en hex para legibilidad |
| `sensor_type` | string (enum) | ✓ | `"ATS"` \| `"PS"` \| `"WS"` \| `"UV"` \| `"HS"` |
| `payload_b64` | string | ✓ | Paquete CCSDS completo (header primario + secundario + payload) codificado en Base64 |
| `crc_computed` | integer | ✓ | CRC-16/CCITT calculado por el simulador; el DAG lo verifica contra el campo CRC del secondary header |
| `produced_utc` | ISO 8601 string | ✓ | Timestamp de producción del mensaje (no del muestreo); solo para auditoría, no para idempotencia |
| `simulator_seed` | integer \| null | ○ | Semilla usada por el simulador; presente en mensajes sintéticos |

### Reglas del consumidor

1. El DAG **no comitea offsets** en `poll_meda_queue`; el commit ocurre en `commit_kafka_offsets` al final del DAG, solo si todas las tareas downstream tuvieron éxito.
2. Si el topic no existe al arrancar el DAG, la tarea `poll_meda_queue` falla con `TopicNotFoundError` descriptivo; ningún objeto Raw se crea parcialmente.
3. Paquetes con `apid` fuera de 0x0C0–0x0CF se descartan en Bronze con `quarantine_reason = 'unknown_apid'` sin propagar a Silver.

---

## Ejemplos por Sensor

### ATS — Air Temperature (APID 0xC0 = 192)

```json
{
  "packet_id": "a3f2b1c9d4e5f607",
  "sol": 100,
  "sclk": 100003600.0,
  "apid": 192,
  "apid_hex": "0xC0",
  "sensor_type": "ATS",
  "payload_b64": "AAAAAAAAAAA=",
  "crc_computed": 61234,
  "produced_utc": "2026-09-29T14:32:00.000Z"
}
```

### PS — Pressure (APID 0xC1 = 193)

```json
{
  "packet_id": "b4e3c2d1e0f9a817",
  "sol": 100,
  "sclk": 100003600.0,
  "apid": 193,
  "apid_hex": "0xC1",
  "sensor_type": "PS",
  "payload_b64": "BBBBBBBBBB0=",
  "crc_computed": 12345,
  "produced_utc": "2026-09-29T14:32:00.100Z"
}
```
