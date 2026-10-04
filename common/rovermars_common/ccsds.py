"""
Funciones puras del protocolo CCSDS compartidas entre servicios.

Antes, `airflow/dags/meda_pipeline.py` hacía `from simulator.ccsds_encoder import
crc16_ccitt` — pero `simulator/` nunca se copia ni se monta dentro de los
contenedores de Airflow (solo existe para el servicio `rover_simulator` y para
Jupyter), así que esa importación fallaba con `ModuleNotFoundError` en cuanto
`validate_bronze` procesaba el primer paquete MEDA (bug real encontrado en
despliegue, ver docs/DESPLIEGUE_MINIPC.md).

La función es pura y sin dependencias, así que vive acá — en `common/`, al que
tanto `simulator/` como `airflow/` ya tienen acceso por PYTHONPATH — en vez de
hacer que un servicio dependa del código fuente de otro.
"""


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE usado en los checksums de CCSDS."""
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
