"""
CCSDS Space Packet Protocol Encoder / Decoder
Consultative Committee for Space Data Systems — CCSDS 133.0-B-2

Packet structure:
  Primary Header (6 bytes):
    ┌─────────────────────────────────────────────────────────────────┐
    │ VER(3) │ TYPE(1) │ SHF(1) │     APID(11)                       │
    ├─────────────────────────────────────────────────────────────────┤
    │ SEQ FLAGS(2) │        PACKET SEQ COUNT(14)                      │
    ├─────────────────────────────────────────────────────────────────┤
    │              PACKET DATA LENGTH(16)                             │
    └─────────────────────────────────────────────────────────────────┘
  Secondary Header (variable, present when SHF=1):
    ┌────────────────────────────────────────────┐
    │ SCLK (8 bytes, 64-bit double)              │
    │ SOL  (4 bytes, uint32)                     │
    │ FILTER WAVELENGTH (2 bytes, uint16 nm)     │
    │ CHECKSUM (2 bytes, CRC-16/CCITT)           │
    └────────────────────────────────────────────┘

  Sequence flags (2 bits):
    00 = continuation segment
    01 = first segment
    10 = last segment
    11 = standalone (unsegmented)

APIDs used in this simulation:
  0x01A5 = Mastcam-Z Left
  0x01A6 = Mastcam-Z Right
  0x01A7 = MEDA telemetry
  0x01B0 = Engineering housekeeping

Reference: CCSDS 133.0-B-2 (Space Packet Protocol)
"""

import random
import struct
from dataclasses import dataclass

# Max bytes in CCSDS packet data field (16-bit length field minus secondary header)
CCSDS_MAX_PAYLOAD_BYTES = 65528
CCSDS_PRIMARY_HEADER_LEN = 6
CCSDS_SECONDARY_HEADER_LEN = 16  # SCLK(8) + SOL(4) + WL(2) + CRC(2)

# Sequence flags
SEQ_STANDALONE   = 0b11
SEQ_FIRST        = 0b01
SEQ_CONTINUATION = 0b00
SEQ_LAST         = 0b10


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE used in CCSDS checksums."""
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


@dataclass
class SpacecraftPacket:
    apid: int
    sequence_flags: int
    sequence_count: int
    sclk: float
    sol: int
    filter_wavelength_nm: int
    payload: bytes

    @property
    def is_first(self) -> bool:
        return self.sequence_flags in (SEQ_FIRST, SEQ_STANDALONE)

    @property
    def is_last(self) -> bool:
        return self.sequence_flags in (SEQ_LAST, SEQ_STANDALONE)

    def to_bytes(self) -> bytes:
        """Serialize to raw CCSDS packet bytes."""
        # Secondary header
        sec_hdr_body = struct.pack(
            ">dIH",
            self.sclk,
            self.sol,
            self.filter_wavelength_nm,
        )
        crc = crc16_ccitt(sec_hdr_body)
        secondary_header = sec_hdr_body + struct.pack(">H", crc)

        data_field = secondary_header + self.payload
        data_length = len(data_field) - 1  # CCSDS data length = total data bytes - 1

        # Primary header
        word1 = (0b000 << 13) | (0 << 12) | (1 << 11) | (self.apid & 0x7FF)
        word2 = (self.sequence_flags << 14) | (self.sequence_count & 0x3FFF)

        primary_header = struct.pack(">HHH", word1, word2, data_length)
        return primary_header + data_field

    @classmethod
    def from_bytes(cls, raw: bytes) -> "SpacecraftPacket":
        """Deserialize from raw bytes."""
        if len(raw) < CCSDS_PRIMARY_HEADER_LEN + CCSDS_SECONDARY_HEADER_LEN:
            raise ValueError("Packet too short")

        word1, word2, data_length = struct.unpack_from(">HHH", raw, 0)
        apid = word1 & 0x7FF
        seq_flags = (word2 >> 14) & 0x3
        seq_count = word2 & 0x3FFF

        # Secondary header starts at offset 6
        sec_off = CCSDS_PRIMARY_HEADER_LEN
        sclk, sol, wl = struct.unpack_from(">dIH", raw, sec_off)
        stored_crc = struct.unpack_from(">H", raw, sec_off + 14)[0]
        computed_crc = crc16_ccitt(raw[sec_off:sec_off + 14])
        if stored_crc != computed_crc:
            raise ValueError(f"CRC mismatch: stored={stored_crc:#06x} computed={computed_crc:#06x}")

        payload_offset = sec_off + CCSDS_SECONDARY_HEADER_LEN
        payload = raw[payload_offset:]

        return cls(
            apid=apid,
            sequence_flags=seq_flags,
            sequence_count=seq_count,
            sclk=sclk,
            sol=sol,
            filter_wavelength_nm=wl,
            payload=payload,
        )

    def __repr__(self):
        flag_map = {SEQ_STANDALONE: "STANDALONE", SEQ_FIRST: "FIRST",
                    SEQ_CONTINUATION: "CONTINUATION", SEQ_LAST: "LAST"}
        return (
            f"SpacecraftPacket(APID={self.apid:#05x}, "
            f"seq={self.sequence_count}, flags={flag_map[self.sequence_flags]}, "
            f"sol={self.sol}, wl={self.filter_wavelength_nm}nm, "
            f"payload={len(self.payload)}B)"
        )


class CCSDSEncoder:
    """
    Fragments large payloads into valid CCSDS Space Packets.
    Handles segmentation according to CCSDS 133.0-B-2 §4.
    """

    MAX_SEGMENT_SIZE = CCSDS_MAX_PAYLOAD_BYTES - CCSDS_SECONDARY_HEADER_LEN

    def __init__(self, apid: int):
        self.apid = apid

    def fragment(
        self,
        payload: bytes,
        sequence_count: int,
        secondary_header: dict,
    ) -> list[SpacecraftPacket]:
        """
        Fragment payload into one or more CCSDS packets.
        secondary_header: dict with keys sclk, filter, sol
        """
        sclk = secondary_header.get("sclk", 0.0)
        sol  = secondary_header.get("sol", 0)
        wl   = secondary_header.get("filter", 0)

        if len(payload) <= self.MAX_SEGMENT_SIZE:
            # Fits in a single standalone packet
            return [SpacecraftPacket(
                apid=self.apid,
                sequence_flags=SEQ_STANDALONE,
                sequence_count=sequence_count % 16384,
                sclk=sclk,
                sol=sol,
                filter_wavelength_nm=wl,
                payload=payload,
            )]

        # Multi-packet segmentation
        packets = []
        offset = 0
        total = len(payload)
        first = True
        seq = sequence_count

        while offset < total:
            chunk = payload[offset:offset + self.MAX_SEGMENT_SIZE]
            offset += len(chunk)
            last = offset >= total

            if first and last:
                flags = SEQ_STANDALONE
            elif first:
                flags = SEQ_FIRST
            elif last:
                flags = SEQ_LAST
            else:
                flags = SEQ_CONTINUATION

            packets.append(SpacecraftPacket(
                apid=self.apid,
                sequence_flags=flags,
                sequence_count=seq % 16384,
                sclk=sclk,
                sol=sol,
                filter_wavelength_nm=wl,
                payload=chunk,
            ))
            seq += 1
            first = False

        return packets


class CCSDSDecoder:
    """
    Reassembles fragmented CCSDS packets back into complete payloads.
    Maintains per-APID reassembly state.
    """

    def __init__(self):
        self._buffers: dict[int, bytearray] = {}
        self._expecting_seq: dict[int, int] = {}

    def feed(self, packet: SpacecraftPacket) -> bytes | None:
        """
        Feed a packet. Returns the complete payload when reassembly
        is done; None if still accumulating.
        Raises ValueError on sequence errors.
        """
        apid = packet.apid

        if packet.is_first:
            self._buffers[apid] = bytearray(packet.payload)
            self._expecting_seq[apid] = (packet.sequence_count + 1) % 16384

        elif apid in self._buffers:
            expected = self._expecting_seq.get(apid)
            if expected is not None and packet.sequence_count != expected:
                raise ValueError(
                    f"Sequence gap APID={apid:#05x}: "
                    f"expected {expected}, got {packet.sequence_count}"
                )
            self._buffers[apid].extend(packet.payload)
            self._expecting_seq[apid] = (packet.sequence_count + 1) % 16384

        if packet.is_last and apid in self._buffers:
            complete = bytes(self._buffers.pop(apid))
            self._expecting_seq.pop(apid, None)
            return complete

        return None


class DSNSimulator:
    """
    Simulates a Deep Space Network ground station receiving CCSDS packets.
    Applies:
    - Variable one-way light delay (3–22 minutes)
    - Bit error rate (BER) simulation
    - Frame loss simulation (dropouts)
    """

    # Typical BER for X-band DSN link at 100+ million km
    XBAND_BER = 1e-9
    PACKET_LOSS_PROBABILITY = 0.02  # DSN link availability ~98%

    def __init__(self, station_name: str = "Goldstone", rng: random.Random | None = None):
        """
        `rng`: generador de números aleatorios opcional. Por defecto (None) se crea
        uno nuevo no determinista -- lo correcto para simular ruido de canal real.
        Pasar un `random.Random(seed)` explícito hace el ruido reproducible, lo que
        permite testear `receive`/`_apply_ber` de forma determinista (ver
        tests/test_dsn_simulator.py) sin depender del estado global de `random`.
        """
        self.station = station_name
        self._decoder = CCSDSDecoder()
        self._rng = rng if rng is not None else random.Random()

    def receive(
        self,
        packet: SpacecraftPacket,
        inject_errors: bool = False,
    ) -> bytes | None:
        """
        Process a received CCSDS packet through the DSN ground station.
        Returns reassembled payload or None if packet was dropped/incomplete.
        """
        raw = packet.to_bytes()

        if inject_errors:
            # Simulate BER
            raw = self._apply_ber(raw)
            # Simulate packet loss
            if self._rng.random() < self.PACKET_LOSS_PROBABILITY:
                return None

        try:
            received = SpacecraftPacket.from_bytes(raw)
        except ValueError as e:
            print(f"[{self.station}] Packet corrupted: {e}")
            return None

        return self._decoder.feed(received)

    def _apply_ber(self, data: bytes) -> bytes:
        """
        Aplica bit errors probabilísticamente según XBAND_BER.

        FIX (ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7): la versión
        anterior calculaba `n_errors = int(n_bits * XBAND_BER)`, que trunca a 0 para
        cualquier paquete CCSDS real -- el tamaño máximo de un paquete (65528 bytes
        = 524224 bits) multiplicado por XBAND_BER=1e-9 da ~0.0005, y `int()` de eso
        es 0 siempre. El resultado: _apply_ber nunca corrompía nada, sin importar la
        semilla ni cuántas veces se llamara -- "determinista" por un bug de
        truncamiento, no por diseño. Ahora se modela como un ensayo de Bernoulli
        independiente por bit, que sí puede producir un error ocasional (la
        probabilidad real y esperada con BER=1e-9 en un paquete de este tamaño
        sigue siendo muy baja, como corresponde a un enlace X-band real).
        """
        result = bytearray(data)
        n_bits = len(result) * 8
        for bit_index in range(n_bits):
            if self._rng.random() < self.XBAND_BER:
                byte_idx, bit_idx = divmod(bit_index, 8)
                result[byte_idx] ^= (1 << bit_idx)
        return bytes(result)
