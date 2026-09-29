-- Staging model: validated MEDA Bronze records (quarantined excluded)
-- Source: raw.meda_bronze_records (populated by validate_bronze task in meda_pipeline DAG)
SELECT
    id,
    packet_id,
    sol,
    sclk,
    apid,
    sensor_type,
    crc_valid,
    schema_valid,
    quarantine_reason,
    arrival_utc,
    payload_size_bytes
FROM {{ source('raw', 'meda_bronze_records') }}
WHERE quarantine_reason IS NULL
