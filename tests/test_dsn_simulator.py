"""
Tests de DSNSimulator (simulator/ccsds_encoder.py) — inyección de ruido de canal
(BER, pérdida de paquetes) determinista cuando se le pasa un `random.Random(seed)`
explícito. Antes usaba el módulo `random` global directamente, lo que hacía
imposible testear `_apply_ber`/la pérdida de paquetes de forma reproducible (ver
Fase 7 de la guía de implementación).
"""

import random

from ccsds_encoder import SEQ_STANDALONE, CCSDSEncoder, DSNSimulator, SpacecraftPacket


def _make_packet(payload=b"mastcamz-test-payload" * 50):
    return SpacecraftPacket(
        apid=0x01A5, sequence_flags=SEQ_STANDALONE, sequence_count=1,
        sclk=1.0, sol=5, filter_wavelength_nm=530, payload=payload,
    )


def test_same_seed_produces_identical_ber_output():
    packet = _make_packet(payload=b"x" * 1000)

    sim_a = DSNSimulator("Goldstone", rng=random.Random(1234))
    sim_b = DSNSimulator("Goldstone", rng=random.Random(1234))
    # BER real (1e-9) es tan baja que un payload de prueba manejable casi nunca
    # produce ni un solo bit corrupto -- se sube artificialmente (solo en el test)
    # para ejercitar la rama de corrupción real, no solo el caso trivial "sin
    # errores". Lo que se testea es el MECANISMO (misma semilla -> mismo ruido),
    # no el valor físico de BER.
    sim_a.XBAND_BER = sim_b.XBAND_BER = 0.01

    corrupted_a = sim_a._apply_ber(packet.to_bytes())
    corrupted_b = sim_b._apply_ber(packet.to_bytes())

    assert corrupted_a == corrupted_b


def test_different_seeds_produce_different_ber_output():
    packet = _make_packet(payload=b"x" * 1000)

    sim_a = DSNSimulator("Goldstone", rng=random.Random(1))
    sim_b = DSNSimulator("Goldstone", rng=random.Random(2))
    sim_a.XBAND_BER = sim_b.XBAND_BER = 0.01  # ver nota en el test anterior

    corrupted_a = sim_a._apply_ber(packet.to_bytes())
    corrupted_b = sim_b._apply_ber(packet.to_bytes())

    assert corrupted_a != corrupted_b


def test_realistic_ber_leaves_a_normal_packet_untouched_almost_always():
    # Con el BER físico real (1e-9) y el tamaño máximo de un paquete CCSDS
    # (65528B), la probabilidad de al menos un bit corrupto es ~0.05% -- así que
    # con una semilla fija arbitraria, lo esperable es que el paquete NO cambie.
    # Esto documenta (no solo testea) que _apply_ber es correcto pero el ruido es
    # extremadamente infrecuente a escala de un solo paquete, algo físicamente
    # correcto para un enlace X-band de espacio profundo.
    packet = _make_packet(payload=b"x" * 60_000)
    sim = DSNSimulator("Goldstone", rng=random.Random(42))
    corrupted = sim._apply_ber(packet.to_bytes())
    assert corrupted == packet.to_bytes()


def test_default_constructor_still_works_without_explicit_rng():
    # No debe romper el uso existente (sin seed = no determinista, comportamiento
    # correcto por defecto para simular ruido de canal real).
    sim = DSNSimulator("Madrid")
    packet = _make_packet()
    result = sim.receive(packet, inject_errors=False)
    assert result == packet.payload


def test_receive_reproducible_packet_loss_with_fixed_seed():
    # Con un rng fijo y muchos intentos, dos simuladores con la misma semilla
    # deben perder/aceptar exactamente los mismos paquetes en el mismo orden.
    packet = _make_packet()

    sim_a = DSNSimulator("Canberra", rng=random.Random(99))
    sim_b = DSNSimulator("Canberra", rng=random.Random(99))

    results_a = [sim_a.receive(packet, inject_errors=True) is not None for _ in range(50)]
    results_b = [sim_b.receive(packet, inject_errors=True) is not None for _ in range(50)]

    assert results_a == results_b


def test_encoder_fragment_is_deterministic_given_same_inputs():
    encoder = CCSDSEncoder(apid=0x01A5)
    payload = b"z" * 300_000
    header = {"sclk": 42.0, "sol": 10, "filter": 530}

    packets_a = encoder.fragment(payload, sequence_count=0, secondary_header=header)
    packets_b = encoder.fragment(payload, sequence_count=0, secondary_header=header)

    assert [p.to_bytes() for p in packets_a] == [p.to_bytes() for p in packets_b]
