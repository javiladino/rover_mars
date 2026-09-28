"""
Tests del encoder/decoder CCSDS 133.0-B-2 (simulator/ccsds_encoder.py).

Cubre: framing correcto, validez de CRC-16/CCITT, fragmentación de payloads
grandes en múltiples paquetes, y reensamblado con detección de huecos de
secuencia — la lógica más "de protocolo real" de todo el proyecto.
"""

import pytest
from ccsds_encoder import (
    CCSDS_MAX_PAYLOAD_BYTES,
    SEQ_STANDALONE,
    CCSDSDecoder,
    CCSDSEncoder,
    SpacecraftPacket,
    crc16_ccitt,
)

APID_MASTCAMZ_LEFT = 0x01A5


def test_crc16_is_deterministic():
    data = b"mastcamz-payload"
    assert crc16_ccitt(data) == crc16_ccitt(data)


def test_crc16_changes_when_data_changes():
    assert crc16_ccitt(b"abc") != crc16_ccitt(b"abd")


def test_packet_roundtrip_preserves_all_fields():
    packet = SpacecraftPacket(
        apid=APID_MASTCAMZ_LEFT,
        sequence_flags=SEQ_STANDALONE,
        sequence_count=42,
        sclk=123456.789,
        sol=100,
        filter_wavelength_nm=530,
        payload=b"\x01\x02\x03\x04",
    )
    raw = packet.to_bytes()
    decoded = SpacecraftPacket.from_bytes(raw)

    assert decoded.apid == packet.apid
    assert decoded.sequence_flags == packet.sequence_flags
    assert decoded.sequence_count == packet.sequence_count
    assert decoded.sclk == pytest.approx(packet.sclk)
    assert decoded.sol == packet.sol
    assert decoded.filter_wavelength_nm == packet.filter_wavelength_nm
    assert decoded.payload == packet.payload


def test_corrupted_secondary_header_raises_crc_mismatch():
    packet = SpacecraftPacket(
        apid=APID_MASTCAMZ_LEFT, sequence_flags=SEQ_STANDALONE,
        sequence_count=1, sclk=1.0, sol=1, filter_wavelength_nm=530,
        payload=b"\xff",
    )
    raw = bytearray(packet.to_bytes())
    raw[6] ^= 0xFF  # corrompe un byte dentro del secondary header (SCLK)

    with pytest.raises(ValueError, match="CRC mismatch"):
        SpacecraftPacket.from_bytes(bytes(raw))


def test_from_bytes_rejects_too_short_packet():
    with pytest.raises(ValueError, match="too short"):
        SpacecraftPacket.from_bytes(b"\x00" * 5)


def test_encoder_fragments_small_payload_into_single_standalone_packet():
    encoder = CCSDSEncoder(apid=APID_MASTCAMZ_LEFT)
    packets = encoder.fragment(
        payload=b"x" * 100,
        sequence_count=0,
        secondary_header={"sclk": 1.0, "sol": 5, "filter": 676},
    )
    assert len(packets) == 1
    assert packets[0].sequence_flags == SEQ_STANDALONE
    assert packets[0].is_first and packets[0].is_last


def test_encoder_fragments_large_payload_into_multiple_packets():
    encoder = CCSDSEncoder(apid=APID_MASTCAMZ_LEFT)
    big_payload = b"x" * int(CCSDS_MAX_PAYLOAD_BYTES * 2.5)
    packets = encoder.fragment(
        payload=big_payload,
        sequence_count=0,
        secondary_header={"sclk": 1.0, "sol": 5, "filter": 676},
    )
    assert len(packets) >= 3
    assert packets[0].is_first and not packets[0].is_last
    assert packets[-1].is_last and not packets[-1].is_first
    assert sum(len(p.payload) for p in packets) == len(big_payload)


def test_decoder_reassembles_fragmented_payload_in_order():
    encoder = CCSDSEncoder(apid=APID_MASTCAMZ_LEFT)
    original = b"mastcamz-image-bytes" * 5000  # fuerza fragmentación
    packets = encoder.fragment(
        payload=original, sequence_count=0,
        secondary_header={"sclk": 1.0, "sol": 5, "filter": 676},
    )

    decoder = CCSDSDecoder()
    result = None
    for p in packets:
        result = decoder.feed(p)

    assert result == original


def test_decoder_raises_on_sequence_gap():
    encoder = CCSDSEncoder(apid=APID_MASTCAMZ_LEFT)
    original = b"y" * int(CCSDS_MAX_PAYLOAD_BYTES * 2.5)
    packets = encoder.fragment(
        payload=original, sequence_count=0,
        secondary_header={"sclk": 1.0, "sol": 5, "filter": 676},
    )

    decoder = CCSDSDecoder()
    decoder.feed(packets[0])
    with pytest.raises(ValueError, match="Sequence gap"):
        decoder.feed(packets[2])  # se salta el paquete intermedio
