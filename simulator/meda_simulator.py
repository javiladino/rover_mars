"""
MEDA Simulator — Mars Environmental Dynamics Analyzer
Genera telemetría ambiental sintética realista y la publica en Kafka.

El simulador produce paquetes CCSDS con un perfil diurno de temperatura basado en
datos de Perseverance en Jezero Crater (Sebastián et al. 2021, JGR Planets).

Uso:
    python meda_simulator.py --seed 42 --sols 1
    python meda_simulator.py --seed 42 --sols 1 --dry-run --output /tmp/run1.bin

Referencia: Sebastián, E. et al. (2021), JGR Planets, 126, e2021JE006823.
DOI: 10.1029/2021JE006823
"""

import argparse
import base64
import hashlib
import json
import math
import os
import random
import struct
from datetime import UTC, datetime
from io import BytesIO

# ── APID y sensor mapping ────────────────────────────────────────────────────
SENSOR_APID = {"ATS": 0xC0, "PS": 0xC1, "WS": 0xC2, "UV": 0xC3, "HS": 0xC4}
SENSOR_TYPE_ID = {"ATS": 1, "PS": 2, "WS": 3, "UV": 4, "HS": 5}

# ── CCSDS layout ─────────────────────────────────────────────────────────────
CCSDS_PRIMARY_HDR_LEN = 6
MEDA_SEC_HDR_FMT = ">dIHH"   # SCLK(float64) + SOL(uint32) + SENSOR_TYPE_ID(uint16) + CRC(uint16)
MEDA_SEC_HDR_LEN = 16

# ── Calibración inversa (DN = valor_físico / GAIN) ───────────────────────────
GAIN_ATS = 0.05
OFFSET_ATS = -120.0
GAIN_PS = 0.0293
GAIN_WS_SPEED = 0.0244
GAIN_WS_DIR = 0.0879
GAIN_UV = 0.00244
GAIN_HS = 0.0244

# ── Modelo de temperatura diurna (research.md §5) ────────────────────────────
T_MEAN = -60.0           # °C
T_AMP = 30.0             # °C (amplitud diurna)
T_PEAK_LMST = 14.0       # h (máximo post-mediodía marciano)
SOL_DURATION_H = 24.659  # h (duración real del sol marciano)
N_SAMPLES_PER_SOL = 24   # muestras uniformes por sol (una por hora marciana)

# ── Base SCLK por sol (s) ────────────────────────────────────────────────────
SOL_SCLK_BASE = 100_000_000.0  # segundos epoch referencia (arbitrario)


def _crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE idéntico al de ccsds_encoder.py."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        crc &= 0xFFFF
    return crc


def _temperature_at_lmst(lmst_h: float) -> float:
    """Modelo sinusoidal de temperatura MEDA (research.md §5).

    Mínimo entre 02:00–06:00 LMST, máximo entre 13:00–15:00 LMST.
    """
    return T_MEAN + T_AMP * math.sin(
        2 * math.pi * (lmst_h - T_PEAK_LMST) / SOL_DURATION_H - math.pi / 2
    )


def _physical_to_dn(physical_value: float, gain: float, offset: float = 0.0, rng: random.Random = None) -> int:
    """Convierte valor físico a DN (calibración inversa) con ruido gaussiano σ=2 DN."""
    noise = (rng or random).gauss(0, 2) if rng else 0
    dn = round((physical_value - offset) / gain + noise)
    return max(0, min(4095, dn))


def _build_ccsds_packet(
    apid: int,
    sensor_type: str,
    sol: int,
    sclk: float,
    payload_dns: list[int],
    seq_count: int,
    corrupt_crc: bool = False,
) -> bytes:
    """Construye un paquete CCSDS MEDA completo con CRC calculado."""
    sensor_type_id = SENSOR_TYPE_ID[sensor_type]

    # Secondary header (placeholder CRC=0)
    sec_hdr_body = struct.pack(MEDA_SEC_HDR_FMT, sclk, sol, sensor_type_id, 0)
    # Payload: DN values as big-endian uint16
    payload = struct.pack(f">{len(payload_dns)}H", *payload_dns)

    data_field_no_crc = sec_hdr_body[:-2] + payload  # without CRC bytes
    crc = _crc16_ccitt(
        struct.pack(">HHH",
                    (0b000 << 13) | (0 << 12) | (1 << 11) | (apid & 0x7FF),
                    (0b11 << 14) | (seq_count & 0x3FFF),
                    MEDA_SEC_HDR_LEN + len(payload) - 1,
                    ) + data_field_no_crc
    )

    if corrupt_crc:
        crc = crc ^ 0xFF  # flip lower byte

    sec_hdr = struct.pack(MEDA_SEC_HDR_FMT, sclk, sol, sensor_type_id, crc)
    data_field = sec_hdr + payload
    data_length = len(data_field) - 1

    word1 = (0b000 << 13) | (0 << 12) | (1 << 11) | (apid & 0x7FF)
    word2 = (0b11 << 14) | (seq_count & 0x3FFF)
    primary_hdr = struct.pack(">HHH", word1, word2, data_length)

    return primary_hdr + data_field


def _build_kafka_message(
    packet_bytes: bytes,
    apid: int,
    sensor_type: str,
    sol: int,
    sclk: float,
    seed: int,
) -> dict:
    """Construye el mensaje JSON Kafka per kafka-topic-schema.md."""
    packet_id = hashlib.sha256(packet_bytes).hexdigest()[:16]
    return {
        "packet_id": packet_id,
        "sol": sol,
        "sclk": sclk,
        "apid": apid,
        "apid_hex": f"0x{apid:02X}",
        "sensor_type": sensor_type,
        "payload_b64": base64.b64encode(packet_bytes).decode(),
        "crc_computed": int.from_bytes(packet_bytes[CCSDS_PRIMARY_HDR_LEN + 14:CCSDS_PRIMARY_HDR_LEN + 16], "big"),
        "produced_utc": datetime.now(UTC).isoformat(),
        "simulator_seed": seed,
    }


def simulate(
    seed: int,
    sols: int,
    topic: str,
    bootstrap: str,
    corrupt_crc_count: int = 0,
    dry_run: bool = False,
    output_path: str | None = None,
) -> list[dict]:
    """Genera y (opcionalmente) publica telemetría MEDA sintética.

    Returns the list of Kafka message dicts (useful for testing / dry-run).
    """
    rng = random.Random(seed)

    messages = []
    raw_bytes_accumulator = BytesIO()
    seq_count = 0
    corrupt_set = set(rng.sample(range(N_SAMPLES_PER_SOL * 5 * sols), k=min(corrupt_crc_count, N_SAMPLES_PER_SOL * 5 * sols)))

    packet_index = 0
    for sol_offset in range(sols):
        sol = sol_offset  # simulate sols 0..sols-1
        sol_sclk_base = SOL_SCLK_BASE + sol * SOL_DURATION_H * 3600.0
        lmst_samples = [i * SOL_DURATION_H / N_SAMPLES_PER_SOL for i in range(N_SAMPLES_PER_SOL)]

        for lmst_h in lmst_samples:
            sclk = sol_sclk_base + lmst_h * 3600.0
            temp_c = _temperature_at_lmst(lmst_h)

            # Synthetic physical values with noise
            pressure_hpa = max(0.0, 7.5 + rng.gauss(0, 0.3))
            wind_speed_ms = max(0.0, 5.0 + rng.gauss(0, 2.0))
            wind_dir_deg = (180.0 + rng.gauss(0, 30.0)) % 360.0
            uv_wm2 = max(0.0, 3.0 * max(0.0, math.sin(math.pi * lmst_h / SOL_DURATION_H)) + rng.gauss(0, 0.1))
            humidity_pct = max(0.0, min(100.0, 2.0 + rng.gauss(0, 0.5)))

            sensor_payloads = {
                "ATS": [_physical_to_dn(temp_c, GAIN_ATS, OFFSET_ATS, rng)],
                "PS":  [_physical_to_dn(pressure_hpa, GAIN_PS, 0.0, rng)],
                "WS":  [_physical_to_dn(wind_speed_ms, GAIN_WS_SPEED, 0.0, rng),
                        _physical_to_dn(wind_dir_deg, GAIN_WS_DIR, 0.0, rng)],
                "UV":  [_physical_to_dn(uv_wm2, GAIN_UV, 0.0, rng)],
                "HS":  [_physical_to_dn(humidity_pct, GAIN_HS, 0.0, rng)],
            }

            for sensor_type, dns in sensor_payloads.items():
                apid = SENSOR_APID[sensor_type]
                corrupt = packet_index in corrupt_set
                pkt = _build_ccsds_packet(apid, sensor_type, sol, sclk, dns, seq_count, corrupt_crc=corrupt)
                msg = _build_kafka_message(pkt, apid, sensor_type, sol, sclk, seed)
                messages.append(msg)
                raw_bytes_accumulator.write(pkt)
                seq_count = (seq_count + 1) % 16384
                packet_index += 1

    if output_path:
        with open(output_path, "wb") as f:
            f.write(raw_bytes_accumulator.getvalue())

    if not dry_run:
        from confluent_kafka import Producer

        producer = Producer({"bootstrap.servers": bootstrap})
        for msg in messages:
            producer.produce(
                topic,
                key=msg["packet_id"].encode(),
                value=json.dumps(msg).encode(),
            )
        producer.flush()

    return messages


def main():
    parser = argparse.ArgumentParser(description="MEDA telemetry simulator for Perseverance rover")
    parser.add_argument("--seed", type=int, required=True, help="Random seed for deterministic output")
    parser.add_argument("--sols", type=int, default=1, help="Number of Martian sols to simulate")
    parser.add_argument("--topic", type=str, default="telemetry.meda.raw")
    parser.add_argument("--bootstrap", type=str, default=os.getenv("KAFKA_BOOTSTRAP", "kafka:9092"))
    parser.add_argument("--corrupt-crc", type=int, default=0, metavar="N",
                        help="Number of packets with flipped CRC (for Bronze quarantine testing)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Kafka publish")
    parser.add_argument("--output", type=str, default=None,
                        help="Path to write concatenated CCSDS bytes (for SHA-256 determinism check)")
    args = parser.parse_args()

    if not (1 <= args.sols <= 999):
        raise ValueError("sols must be in [1, 999]")

    msgs = simulate(
        seed=args.seed,
        sols=args.sols,
        topic=args.topic,
        bootstrap=args.bootstrap,
        corrupt_crc_count=args.corrupt_crc,
        dry_run=args.dry_run,
        output_path=args.output,
    )
    print(f"Generated {len(msgs)} MEDA packets ({args.sols} sol(s), seed={args.seed})")
    if args.dry_run:
        print("Dry-run mode: no messages published to Kafka")


if __name__ == "__main__":
    main()
