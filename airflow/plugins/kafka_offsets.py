"""
Bookkeeping puro de offsets de Kafka — separado del consumo real (I/O) para poder
testearlo sin un broker Kafka real.

Contexto (ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7): antes,
`poll_bronze_queue` hacía `consumer.commit(message=msg)` inmediatamente después de
leer cada mensaje, ANTES de que el resto del pipeline (validación, calibración,
Silver, Postgres, dbt) confirmara éxito. Si cualquiera de esas tareas fallaba, el
mensaje ya estaba comiteado y se perdía para siempre — el reintento de Airflow no lo
volvía a ver. Ahora `poll_bronze_queue` solo registra qué offset habría que comitear
por partición (con `track_max_offset`), y una tarea `commit_kafka_offsets` al final
del DAG hace el commit real solo si todo lo anterior tuvo éxito.

Determinismo/idempotencia: `track_max_offset` es monótona — aplicar offsets fuera de
orden o repetidos nunca retrocede el valor guardado, así que recalcular sobre el
mismo lote de mensajes (p.ej. en un reintento) siempre converge al mismo resultado.
"""

OffsetKey = tuple[str, int]  # (topic, partition)


def track_max_offset(offsets: dict[OffsetKey, int], topic: str, partition: int, offset: int) -> dict[OffsetKey, int]:
    """
    Actualiza `offsets` (in-place, y lo devuelve) con el próximo offset a comitear
    para (topic, partition): el mayor `offset` visto + 1, que es la semántica
    estándar de commit de Kafka (offset del PRÓXIMO mensaje a leer, no del último leído).
    """
    key = (topic, partition)
    candidate = offset + 1
    if key not in offsets or candidate > offsets[key]:
        offsets[key] = candidate
    return offsets


def offsets_to_commit_list(offsets: dict[OffsetKey, int]) -> list[dict]:
    """Convierte el dict interno {(topic, partition): offset} a una lista serializable en XCom/JSON."""
    return [{"topic": t, "partition": p, "offset": o} for (t, p), o in offsets.items()]
