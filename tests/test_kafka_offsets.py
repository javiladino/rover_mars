"""
Tests de airflow/plugins/kafka_offsets.py — bookkeeping de offsets separado del
consumo real de Kafka (ver Fase 7 de la guía de implementación).
"""

from kafka_offsets import offsets_to_commit_list, track_max_offset


def test_track_max_offset_records_next_offset_to_commit():
    offsets = {}
    track_max_offset(offsets, "etl.bronze.ready", 0, 41)
    # El offset a comitear es el del PRÓXIMO mensaje a leer (41 + 1), semántica
    # estándar de Kafka.
    assert offsets[("etl.bronze.ready", 0)] == 42


def test_track_max_offset_keeps_the_highest_seen_per_partition():
    offsets = {}
    track_max_offset(offsets, "t", 0, 5)
    track_max_offset(offsets, "t", 0, 10)
    assert offsets[("t", 0)] == 11


def test_track_max_offset_is_monotonic_even_out_of_order():
    # Un mensaje más viejo llegando después de uno más nuevo no debe retroceder
    # el offset a comitear -- esto es lo que hace que recalcular sobre el mismo
    # lote (p.ej. en un reintento de Airflow) siempre converja al mismo resultado.
    offsets = {}
    track_max_offset(offsets, "t", 0, 10)
    track_max_offset(offsets, "t", 0, 3)
    assert offsets[("t", 0)] == 11


def test_track_max_offset_tracks_partitions_independently():
    offsets = {}
    track_max_offset(offsets, "t", 0, 5)
    track_max_offset(offsets, "t", 1, 99)
    assert offsets[("t", 0)] == 6
    assert offsets[("t", 1)] == 100


def test_track_max_offset_returns_the_same_dict_it_mutates():
    offsets = {}
    result = track_max_offset(offsets, "t", 0, 1)
    assert result is offsets


def test_offsets_to_commit_list_serializes_to_plain_dicts():
    offsets = {("etl.bronze.ready", 0): 5, ("etl.bronze.ready", 1): 12}
    result = offsets_to_commit_list(offsets)
    assert {"topic": "etl.bronze.ready", "partition": 0, "offset": 5} in result
    assert {"topic": "etl.bronze.ready", "partition": 1, "offset": 12} in result
    assert len(result) == 2


def test_offsets_to_commit_list_empty_dict_gives_empty_list():
    assert offsets_to_commit_list({}) == []


def test_reprocessing_the_same_batch_converges_to_the_same_offsets():
    # Simula un reintento de Airflow: el mismo lote de mensajes se vuelve a
    # procesar (porque el commit anterior nunca ocurrió) y el resultado final
    # de offsets a comitear debe ser idéntico -- es la propiedad de idempotencia
    # que justifica diferir el commit al final del DAG.
    batch = [("etl.bronze.ready", 0, 1), ("etl.bronze.ready", 0, 2), ("etl.bronze.ready", 1, 7)]

    run1: dict = {}
    for topic, partition, offset in batch:
        track_max_offset(run1, topic, partition, offset)

    run2: dict = {}
    for topic, partition, offset in batch:
        track_max_offset(run2, topic, partition, offset)

    assert offsets_to_commit_list(run1) == offsets_to_commit_list(run2)
