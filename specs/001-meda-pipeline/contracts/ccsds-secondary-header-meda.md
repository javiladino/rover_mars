# Contrato — CCSDS Secondary Header MEDA

**Branch**: `001-meda-pipeline` | **Date**: 2026-09-29  
**Referencia**: CCSDS 133.0-B-2 (Space Packet Protocol)

---

## Estructura del Paquete CCSDS MEDA

```
┌─────────────────────────────────────────────────────────────────┐
│               PRIMARY HEADER (6 bytes — igual que Mastcam-Z)    │
├────────┬──────┬──────┬─────────────────────────────────────────┤
│VER (3) │TYPE  │ SHF  │              APID (11 bits)              │
│  0b000 │  0   │   1  │  0x0C0 a 0x0C4 (ATS/PS/WS/UV/HS)       │
├────────┴──────┴──────┴─────────────────────────────────────────┤
│ SEQ FLAGS (2) │         PACKET SEQ COUNT (14 bits)              │
│     0b11      │          incremental por sensor                 │
├───────────────────────────────────────────────────────────────── ┤
│                  PACKET DATA LENGTH (16 bits)                   │
│         = len(secondary_header) + len(payload) - 1             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│           SECONDARY HEADER MEDA (16 bytes — SHF = 1)            │
├────────────────────────────────────────────────────────────────┤
│  SCLK          — 8 bytes, float64 big-endian                    │
│                  Spacecraft Clock (segundos desde epoch misión) │
├────────────────────────────────────────────────────────────────┤
│  SOL           — 4 bytes, uint32 big-endian                     │
│                  Sol marciano (0–999)                           │
├────────────────────────────────────────────────────────────────┤
│  SENSOR_TYPE_ID — 2 bytes, uint16 big-endian                    │
│                  1=ATS, 2=PS, 3=WS, 4=UV, 5=HS                │
├────────────────────────────────────────────────────────────────┤
│  CRC-16/CCITT  — 2 bytes, uint16 big-endian                     │
│                  Calculado sobre todo el paquete excepto estos  │
│                  2 bytes finales                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    PAYLOAD (variable)                            │
│  DN values del sensor, codificados en big-endian uint16         │
│  - ATS: 1 × uint16 (temperature DN)                            │
│  - PS:  1 × uint16 (pressure DN)                               │
│  - WS:  2 × uint16 (speed DN, direction DN)                     │
│  - UV:  1 × uint16 (irradiance DN)                              │
│  - HS:  1 × uint16 (humidity DN)                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tabla de SENSOR_TYPE_ID

| sensor_type | SENSOR_TYPE_ID | APID (hex) | Payload size (bytes) |
|-------------|---------------|------------|---------------------|
| ATS         | 1             | 0x0C0      | 2 (1 × uint16) |
| PS          | 2             | 0x0C1      | 2 (1 × uint16) |
| WS          | 3             | 0x0C2      | 4 (2 × uint16) |
| UV          | 4             | 0x0C3      | 2 (1 × uint16) |
| HS          | 5             | 0x0C4      | 2 (1 × uint16) |

---

## Diferencias respecto a Mastcam-Z

El secondary header MEDA tiene la **misma longitud** (16 bytes) que el de Mastcam-Z, pero reemplaza el campo `FILTER_WAVELENGTH` por `SENSOR_TYPE_ID`:

| Offset | Mastcam-Z | MEDA |
|--------|-----------|------|
| 0–7    | SCLK (float64) | SCLK (float64) |
| 8–11   | SOL (uint32) | SOL (uint32) |
| 12–13  | FILTER_WAVELENGTH (uint16, nm) | SENSOR_TYPE_ID (uint16) |
| 14–15  | CRC-16/CCITT | CRC-16/CCITT |

---

## Struct Python (para `meda_simulator.py`)

```python
import struct

MEDA_SECONDARY_HEADER_FMT = ">dIHH"  # big-endian: float64 + uint32 + uint16 + uint16
MEDA_SECONDARY_HEADER_LEN = 16       # bytes

def pack_meda_secondary_header(
    sclk: float,
    sol: int,
    sensor_type_id: int,  # 1=ATS, 2=PS, 3=WS, 4=UV, 5=HS
    crc: int = 0,
) -> bytes:
    return struct.pack(MEDA_SECONDARY_HEADER_FMT, sclk, sol, sensor_type_id, crc)

def unpack_meda_secondary_header(data: bytes) -> dict:
    sclk, sol, sensor_type_id, crc = struct.unpack(
        MEDA_SECONDARY_HEADER_FMT, data[:MEDA_SECONDARY_HEADER_LEN]
    )
    return {"sclk": sclk, "sol": sol, "sensor_type_id": sensor_type_id, "crc": crc}
```

---

## Validación de CRC

El CRC-16/CCITT se calcula sobre el paquete completo excepto los 2 bytes del campo CRC mismo (igual que Mastcam-Z, ver `simulator/ccsds_encoder.py :: crc16_ccitt`). Para validar en el DAG:

```python
from simulator.ccsds_encoder import crc16_ccitt

def validate_meda_crc(raw_packet: bytes) -> bool:
    """Verifica el CRC-16/CCITT de un paquete CCSDS MEDA."""
    # CRC está en los últimos 2 bytes del secondary header (bytes 20–21 del paquete)
    crc_offset = 6 + 14  # primary header + secondary header sin CRC
    expected_crc = int.from_bytes(raw_packet[crc_offset:crc_offset+2], "big")
    computed_crc = crc16_ccitt(raw_packet[:crc_offset] + raw_packet[crc_offset+2:])
    return computed_crc == expected_crc
```
