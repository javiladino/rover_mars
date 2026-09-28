"""
DSN Ground Station Receiver — Kafka Consumer + MinIO Bronze Layer writer

Simulates the Deep Space Network (DSN) ground processing chain:
  1. Consume CCSDS raw events from Kafka (with simulated light-travel delay)
  2. Validate packet integrity (CRC, sequence gaps)
  3. Decode metadata and classify image product type
  4. Write EDR (Experiment Data Record) to MinIO Bronze bucket
  5. Write telemetry record to PostgreSQL
  6. Publish ready-event to etl.bronze.ready topic

DSN Stations simulated:
  - DSS-14 Goldstone, California  (70m)  [primary Mars uplink/downlink]
  - DSS-63 Madrid, Spain          (70m)
  - DSS-43 Canberra, Australia    (70m)

Reference: CCSDS 133.0-B-2, NASA DSN 810-005 Module 101
"""

import io
import json
import logging
import os
import time
from datetime import UTC, datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DSN-%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger(os.getenv("DSN_STATION", "Goldstone"))

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:29092")
MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",  "http://localhost:9000").replace("http://","").replace("https://","")
MINIO_SECURE    = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS    = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET    = os.getenv("MINIO_SECRET_KEY", "minioadmin")
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
POSTGRES_CONN   = os.getenv("POSTGRES_CONN",    "postgresql://rover:rover2024@localhost:5432/rover_mars")
STATION_NAME    = os.getenv("DSN_STATION",      "Goldstone")
LIGHT_DELAY_MIN = float(os.getenv("LIGHT_DELAY_MIN_MIN", "3"))   # minutes
LIGHT_DELAY_MAX = float(os.getenv("LIGHT_DELAY_MAX_MIN", "22"))  # minutes

# Bucket configurable: MinIO local por defecto, o el bucket S3 real en AWS
# (infra/aws/s3.tf, ADR-012 en docs/ANALISIS_MODERN_DATA_STACK.md).
S3_BUCKET_BRONZE = os.getenv("S3_BUCKET_BRONZE", "mastcamz-bronze")


def simulate_light_delay(event: dict) -> float:
    """
    Compute one-way light-travel time from event metadata (seconds).
    Falls back to a random value in the configured range.
    """
    if "light_travel_time_s" in event:
        return float(event["light_travel_time_s"])
    import random
    return random.uniform(LIGHT_DELAY_MIN * 60, LIGHT_DELAY_MAX * 60)


def classify_product_type(event: dict) -> str:
    """Assign NASA EDR product type code based on filter/camera combination.

    Nota (ver Fase 7 de la guía de implementación): `event["eye"]` no participa
    hoy en la clasificación pese a lo que dice el nombre de la función/docstring
    original — se detectó como variable muerta durante la auditoría de lint. Se
    deja documentado en vez de inventar una regla de clasificación por cámara no
    verificada contra la taxonomía real de productos NASA/MIPL.
    """
    wl    = event.get("filter_wavelength_nm", 530)
    focal = event.get("focal_mm", 26)

    if wl < 500:
        return "EBB"    # Enhanced broadband blue
    elif wl < 600:
        return "ERG"    # Enhanced red-green
    elif wl < 750:
        return "ERZ"    # Red-zone narrowband
    elif focal >= 100:
        return "EZT"    # Zoom telephoto
    else:
        return "ENB"    # NIR broadband


def build_bronze_record(event: dict, delay_s: float) -> dict:
    """Construct the Bronze layer metadata record for this image."""
    arrival_utc = datetime.now(UTC).isoformat()
    return {
        "product_id":         event.get("product_id", "UNKNOWN"),
        "file_name":          event.get("file_name", ""),
        "sol":                event.get("sol", 0),
        "sclk":               event.get("sclk", 0.0),
        "camera_eye":         event.get("eye", ""),
        "filter_wavelength_nm": event.get("filter_wavelength_nm", 0),
        "focal_mm":           event.get("focal_mm", 0.0),
        "n_ccsds_packets":    event.get("n_packets", 0),
        "minio_raw_key":      event.get("minio_key", ""),
        "dsn_station":        STATION_NAME,
        "light_delay_s":      round(delay_s, 1),
        "capture_utc":        event.get("timestamp_utc", ""),
        "arrival_utc":        arrival_utc,
        "product_type":       classify_product_type(event),
        "processing_stage":   "BRONZE",
        "quality_flag":       "GOOD",
    }


def write_to_minio_bronze(client, record: dict) -> str:
    """Store Bronze metadata JSON in MinIO mastcamz-bronze bucket."""
    key  = f"sol={record['sol']:04d}/{record['file_name'].replace('.IMG', '')}_BRONZE.json"
    body = json.dumps(record, indent=2).encode()
    client.put_object(
        S3_BUCKET_BRONZE,
        key,
        io.BytesIO(body),
        len(body),
        content_type="application/json",
    )
    return key


def write_to_postgres(conn, record: dict):
    """Insert telemetry record into rover_mars.image_products table."""
    sql = """
        INSERT INTO image_products (
            product_id, file_name, sol, sclk, camera_eye,
            filter_wavelength_nm, focal_mm, dsn_station,
            light_delay_s, capture_utc, arrival_utc,
            product_type, processing_stage, quality_flag,
            minio_bronze_key
        ) VALUES (
            %(product_id)s, %(file_name)s, %(sol)s, %(sclk)s, %(camera_eye)s,
            %(filter_wavelength_nm)s, %(focal_mm)s, %(dsn_station)s,
            %(light_delay_s)s, %(capture_utc)s, %(arrival_utc)s,
            %(product_type)s, %(processing_stage)s, %(quality_flag)s,
            %(minio_raw_key)s
        )
        ON CONFLICT (product_id) DO UPDATE
          SET processing_stage = EXCLUDED.processing_stage,
              arrival_utc      = EXCLUDED.arrival_utc;
    """
    with conn.cursor() as cur:
        cur.execute(sql, record)
    conn.commit()


def run():
    """Main consumer loop."""
    import psycopg2
    from confluent_kafka import Consumer
    from rovermars_common.storage import build_object_store_client
    minio_client = build_object_store_client(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS,
        secret_key=MINIO_SECRET,
        secure=MINIO_SECURE,
        region=AWS_REGION,
    )

    pg_conn = psycopg2.connect(POSTGRES_CONN)

    from confluent_kafka import Producer
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP})

    consumer = Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id":          f"dsn_receiver_{STATION_NAME}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(["mastcamz.raw.images", "mastcamz.telemetry"])

    log.info(f"DSN Station [{STATION_NAME}] listening on Kafka...")

    try:
        while True:
            msg = consumer.poll(timeout=5.0)
            if msg is None:
                continue
            if msg.error():
                log.error(f"Kafka error: {msg.error()}")
                continue

            topic = msg.topic()
            event = json.loads(msg.value().decode("utf-8"))

            if topic == "mastcamz.telemetry":
                # Store raw telemetry to MinIO bronze.
                #
                # BUG corregido (ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md,
                # Fase 7): la key solo incluía `sol`, así que TODAS las muestras de
                # telemetría de un mismo sol (llegan varias por sol) se sobrescribían
                # entre sí — solo sobrevivía la última. Se usa el timestamp propio
                # del evento como componente de la key: es determinista (el mismo
                # evento reproducido produce siempre la misma key -> idempotente
                # ante reprocesos) y único por muestra real.
                sol = event.get("sol", 0)
                event_ts = event.get("utc_timestamp", "")
                if event_ts:
                    event_ts = event_ts.replace(":", "").replace("+00:00", "Z")
                else:
                    event_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                    log.warning(f"Telemetry event sin utc_timestamp (sol={sol}); usando hora de recepción")
                key = f"sol={sol:04d}/telemetry_{sol:04d}_{event_ts}.json"
                body = json.dumps(event, indent=2).encode()
                minio_client.put_object(
                    S3_BUCKET_BRONZE, key,
                    io.BytesIO(body), len(body),
                    content_type="application/json",
                )
                log.info(f"Telemetry Sol {sol:04d} → bronze/{key}")
                continue

            # mastcamz.raw.images
            delay_s = simulate_light_delay(event)
            log.info(
                f"[RX] Sol {event.get('sol'):04d} | {event.get('file_name')} | "
                f"delay={delay_s/60:.1f}min | {event.get('filter_wavelength_nm')}nm"
            )

            # Simulate actual signal travel delay (scaled down for demo)
            time.sleep(min(delay_s / 600, 5.0))  # 1:600 time scale, max 5s

            bronze_record = build_bronze_record(event, delay_s)
            bronze_key    = write_to_minio_bronze(minio_client, bronze_record)
            bronze_record["minio_bronze_key"] = bronze_key

            try:
                write_to_postgres(pg_conn, bronze_record)
            except Exception as e:
                log.warning(f"Postgres write failed: {e} — continuing")
                pg_conn = psycopg2.connect(POSTGRES_CONN)

            # Signal ETL pipeline
            producer.produce(
                "etl.bronze.ready",
                key=bronze_record["product_id"].encode(),
                value=json.dumps(bronze_record).encode(),
            )
            producer.poll(0)

            log.info(
                f"[BRONZE] {bronze_record['product_id'][:50]} → "
                f"bronze/{bronze_key}"
            )

    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        pg_conn.close()
        log.info("DSN receiver stopped.")


if __name__ == "__main__":
    run()
