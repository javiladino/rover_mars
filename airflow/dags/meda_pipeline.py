"""
Airflow DAG — MEDA Full ETL Pipeline
Orquesta el ciclo de vida completo de telemetría MEDA (Mars Environmental Dynamics
Analyzer) desde Raw Kafka hasta Gold analítico, siguiendo la arquitectura Medallion.

Pipeline stages:
  RAW    → Paquetes CCSDS binarios en MinIO meda-raw (inmutables)
  BRONZE → Metadatos de validación en Postgres raw.meda_bronze_records
  SILVER → Lecturas calibradas consolidadas en science.meda_silver_readings
  GOLD   → Agregados por sol en MinIO meda-gold + dbt marts.fct_meda_sol_summary

Tasks:
   1. poll_meda_queue         — Consume Kafka telemetry.meda.raw (sin commit de offsets)
   2. ingest_raw              — Escribe paquetes CCSDS a MinIO meda-raw (inmutable)
   3. validate_bronze         — Valida CRC, APID, tamaño, campos; upsert meda_bronze_records
   4. calibrate_silver        — Calibra DN→SI, consolida por (sol,sclk)
   5. write_silver_minio      — Persiste lecturas Silver JSON en MinIO meda-silver
   6. update_silver_postgres  — Upsert science.meda_silver_readings + PostGIS
   7. detect_anomalies        — Aplica reglas MEDA, actualiza anomaly_flag
   8. build_gold_aggregates   — Agrega por sol, escribe JSON a meda-gold (ADR-001)
   9. dbt_build               — Modelos dbt staging + fct_meda_sol_summary
  10. commit_kafka_offsets     — Commit Kafka solo si todo lo anterior tuvo éxito (RF-009)
  11. notify                  — Log métricas de completitud del pipeline

Idempotencia: claves MinIO deterministas (sol/apid/packet_id.bin), upserts ON CONFLICT
en Postgres, Kafka commit diferido — reprocesar el mismo lote es seguro (at-least-once
+ writes idempotentes = efecto exactly-once).
"""

import base64
import hashlib
import io
import json
import logging
import os
import struct
from collections import defaultdict
from datetime import datetime, timedelta

import psycopg2
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from meda_anomaly_rules import detect_anomalies as meda_detect_anomalies
from meda_calibration import (
    calibrate_ats,
    calibrate_hs,
    calibrate_ps,
    calibrate_uv,
    calibrate_ws_dir,
    calibrate_ws_speed,
)

from airflow import DAG

log = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").replace("http://", "").replace("https://", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET = os.getenv("MINIO_SECRET_KEY", "minioadmin")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
POSTGRES_CONN = os.getenv("POSTGRES_CONN", "postgresql://rover:rover2024@postgres:5432/rover_mars")
DBT_PROJECT_DIR = os.getenv("DBT_PROJECT_DIR", "/opt/airflow/dbt")
DBT_PROFILES_DIR = os.getenv("DBT_PROFILES_DIR", "/opt/airflow/dbt")

MEDA_BUCKET_RAW = os.getenv("MEDA_S3_BUCKET_RAW", "meda-raw")
MEDA_BUCKET_SILVER = os.getenv("MEDA_S3_BUCKET_SILVER", "meda-silver")
MEDA_BUCKET_GOLD = os.getenv("MEDA_S3_BUCKET_GOLD", "meda-gold")

MEDA_KAFKA_TOPIC = "telemetry.meda.raw"
MEDA_CONSUMER_GROUP = os.getenv("MEDA_KAFKA_CONSUMER_GROUP", "meda_pipeline_dag")
MEDA_BATCH_SIZE = int(os.getenv("MEDA_BATCH_SIZE", "100"))

# MEDA APID range: 0x0C0 (192) – 0x0C4 (196) per research.md §1
MEDA_APID_MIN = 192
MEDA_APID_MAX = 207  # full reserved range 0x0C0–0x0CF

# CCSDS secondary header layout (research.md §2): >dIHH = SCLK + SOL + SENSOR_TYPE_ID + CRC
MEDA_SEC_HDR_FMT = ">dIHH"
MEDA_SEC_HDR_LEN = 16
CCSDS_PRIMARY_HDR_LEN = 6
MEDA_CRC_OFFSET = CCSDS_PRIMARY_HDR_LEN + 14  # bytes before the 2-byte CRC field

SENSOR_ID_MAP = {1: "ATS", 2: "PS", 3: "WS", 4: "UV", 5: "HS"}

SOL_DURATION_S = 24.659 * 3600  # seconds per Martian sol


def _get_minio():
    from rovermars_common.storage import build_object_store_client
    return build_object_store_client(
        endpoint=MINIO_ENDPOINT, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET,
        secure=MINIO_SECURE, region=AWS_REGION,
    )


def _get_pg():
    return psycopg2.connect(POSTGRES_CONN)


def _crc16_ccitt(data: bytes) -> int:
    from simulator.ccsds_encoder import crc16_ccitt
    return crc16_ccitt(data)


# ── DAG Definition ────────────────────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "rover",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=30),
}

with DAG(
    dag_id="meda_full_pipeline",
    description="MEDA ETL: Kafka → Raw → Bronze → Silver → Gold (Medallion)",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["meda", "pipeline", "mars", "perseverance"],
) as dag:

    # ── TASK 1: Poll Kafka ────────────────────────────────────
    def poll_meda_queue(**context):
        """Consume hasta MEDA_BATCH_SIZE mensajes de telemetry.meda.raw.

        No comitea offsets (enable.auto.commit=False). El commit real ocurre en
        commit_kafka_offsets al final del DAG, solo si todo lo anterior tuvo éxito.
        """
        from confluent_kafka import Consumer, KafkaError
        from kafka_offsets import offsets_to_commit_list, track_max_offset

        consumer = Consumer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": MEDA_CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 60000,
        })

        # Verify topic exists before consuming
        metadata = consumer.list_topics(timeout=10)
        if MEDA_KAFKA_TOPIC not in metadata.topics:
            consumer.close()
            raise RuntimeError(f"TopicNotFoundError: {MEDA_KAFKA_TOPIC} not found")

        consumer.subscribe([MEDA_KAFKA_TOPIC])

        raw_messages = []
        offsets: dict = {}

        while len(raw_messages) < MEDA_BATCH_SIZE:
            msg = consumer.poll(timeout=30.0)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.warning(f"Kafka error: {msg.error()}")
                continue
            try:
                raw_messages.append(json.loads(msg.value().decode("utf-8")))
                track_max_offset(offsets, msg.topic(), msg.partition(), msg.offset())
            except Exception as e:
                log.warning(f"Parse error: {e}")

        consumer.close()
        log.info(f"Polled {len(raw_messages)} MEDA messages (offsets not committed yet)")
        context["ti"].xcom_push(key="raw_messages", value=raw_messages)
        context["ti"].xcom_push(key="kafka_offsets", value=offsets_to_commit_list(offsets))

    poll_task = PythonOperator(task_id="poll_meda_queue", python_callable=poll_meda_queue)

    # ── TASK 2: Ingest Raw ────────────────────────────────────
    def ingest_raw(**context):
        """Escribe cada paquete CCSDS a MinIO meda-raw con clave determinista.

        Clave: {sol:04d}/0x{apid:02x}/{packet_id}.bin
        Inmutable: si el objeto ya existe, se omite el PUT (RF-003, CE-002).
        """
        from minio.error import S3Error

        raw_messages = context["ti"].xcom_pull(key="raw_messages", task_ids="poll_meda_queue")
        client = _get_minio()
        enriched = []

        for msg in raw_messages:
            payload_bytes = base64.b64decode(msg["payload_b64"])
            packet_id = hashlib.sha256(payload_bytes).hexdigest()[:16]
            apid = int(msg["apid"])
            sol = int(msg["sol"])
            minio_key = f"{sol:04d}/0x{apid:02x}/{packet_id}.bin"

            try:
                client.stat_object(MEDA_BUCKET_RAW, minio_key)
                log.info(f"Raw object exists (skipping): {minio_key}")
            except S3Error:
                client.put_object(
                    MEDA_BUCKET_RAW, minio_key,
                    io.BytesIO(payload_bytes), len(payload_bytes),
                )

            enriched.append({**msg, "packet_id": packet_id, "minio_raw_key": minio_key})

        log.info(f"Ingested {len(enriched)} raw MEDA packets")
        context["ti"].xcom_push(key="enriched_messages", value=enriched)

    ingest_task = PythonOperator(task_id="ingest_raw", python_callable=ingest_raw)

    # ── TASK 3: Validate Bronze ───────────────────────────────
    def validate_bronze(**context):
        """Valida CRC, APID, tamaño y campos obligatorios; upsert meda_bronze_records.

        Paquetes con CRC inválido → quarantine_reason='crc_mismatch' (T028).
        Paquetes con APID fuera de rango → quarantine_reason='unknown_apid'.
        Solo los que pasan TODAS las validaciones se propagan a Silver.
        """
        enriched = context["ti"].xcom_pull(key="enriched_messages", task_ids="ingest_raw")
        conn = _get_pg()
        bronze_records = []

        sql = """
            INSERT INTO raw.meda_bronze_records
                (packet_id, sol, sclk, apid, sensor_type, minio_raw_key,
                 crc_valid, schema_valid, quarantine_reason, payload_size_bytes)
            VALUES
                (%(packet_id)s, %(sol)s, %(sclk)s, %(apid)s, %(sensor_type)s,
                 %(minio_raw_key)s, %(crc_valid)s, %(schema_valid)s,
                 %(quarantine_reason)s, %(payload_size_bytes)s)
            ON CONFLICT (packet_id) DO UPDATE SET
                crc_valid         = EXCLUDED.crc_valid,
                schema_valid      = EXCLUDED.schema_valid,
                quarantine_reason = EXCLUDED.quarantine_reason,
                minio_raw_key     = EXCLUDED.minio_raw_key,
                payload_size_bytes = EXCLUDED.payload_size_bytes
        """

        with conn.cursor() as cur:
            for msg in enriched:
                payload_bytes = base64.b64decode(msg["payload_b64"])
                payload_size = len(payload_bytes)
                apid = int(msg["apid"])
                sol = int(msg["sol"])
                sclk = float(msg["sclk"])
                sensor_type = msg.get("sensor_type", "")
                packet_id = msg["packet_id"]
                minio_raw_key = msg["minio_raw_key"]

                # (1) Validate CRC-16/CCITT
                if len(payload_bytes) >= MEDA_CRC_OFFSET + 2:
                    expected_crc = int.from_bytes(payload_bytes[MEDA_CRC_OFFSET:MEDA_CRC_OFFSET + 2], "big")
                    computed_crc = _crc16_ccitt(
                        payload_bytes[:MEDA_CRC_OFFSET] + payload_bytes[MEDA_CRC_OFFSET + 2:]
                    )
                    crc_valid = computed_crc == expected_crc
                else:
                    crc_valid = False

                # (2-5) Schema checks — evaluated only if CRC passed
                schema_valid = True
                quarantine_reason = None

                if not crc_valid:
                    schema_valid = False
                    quarantine_reason = "crc_mismatch"
                elif not (MEDA_APID_MIN <= apid <= MEDA_APID_MAX):
                    schema_valid = False
                    quarantine_reason = "unknown_apid"
                elif payload_size > 65528:
                    schema_valid = False
                    quarantine_reason = "payload_too_large"
                elif not all([sol is not None, sclk is not None, sensor_type]):
                    schema_valid = False
                    quarantine_reason = "missing_fields"

                record = {
                    "packet_id": packet_id,
                    "sol": sol,
                    "sclk": sclk,
                    "apid": apid,
                    "sensor_type": sensor_type if sensor_type else "ATS",
                    "minio_raw_key": minio_raw_key,
                    "crc_valid": crc_valid,
                    "schema_valid": schema_valid,
                    "quarantine_reason": quarantine_reason,
                    "payload_size_bytes": payload_size,
                }
                cur.execute(sql, record)
                bronze_records.append(record)

        conn.commit()
        conn.close()
        log.info(f"Bronze: upserted {len(bronze_records)} records")
        context["ti"].xcom_push(key="bronze_records", value=bronze_records)

    validate_task = PythonOperator(task_id="validate_bronze", python_callable=validate_bronze)

    # ── TASK 4: Calibrate Silver ──────────────────────────────
    def calibrate_silver(**context):
        """Calibra DN→SI y consolida registros Bronze válidos por (sol, sclk).

        Solo procesa registros con quarantine_reason IS NULL (crc_valid AND schema_valid).
        Consulta telemetry_records para obtener la posición del rover más cercana en LMST.
        """
        bronze_records = context["ti"].xcom_pull(key="bronze_records", task_ids="validate_bronze")
        conn = _get_pg()

        valid_records = [r for r in bronze_records if r.get("quarantine_reason") is None]
        groups: dict = defaultdict(list)
        for rec in valid_records:
            groups[(rec["sol"], rec["sclk"])].append(rec)

        silver_rows = []
        for (sol, sclk), group in groups.items():
            lmst_h = (sclk % SOL_DURATION_S) / 3600.0

            # Rover position lookup from telemetry_records (T029)
            rover_lat = rover_lon = None
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT latitude_deg, longitude_deg
                        FROM telemetry_records
                        WHERE sol = %s
                        ORDER BY ABS(local_mean_solar_time - %s) NULLS LAST
                        LIMIT 1
                        """,
                        (sol, lmst_h),
                    )
                    row = cur.fetchone()
                    if row:
                        rover_lat, rover_lon = row
            except Exception as e:
                log.warning(f"Rover position lookup failed for sol={sol}: {e}")

            silver = {
                "sol": sol,
                "sclk": sclk,
                "lmst_h": lmst_h,
                "temperature_ats_c": None,
                "pressure_hpa": None,
                "wind_speed_ms": None,
                "wind_direction_deg": None,
                "uv_irradiance_w_m2": None,
                "humidity_pct": None,
                "has_ats": False,
                "has_ps": False,
                "has_ws": False,
                "has_uv": False,
                "has_hs": False,
                "anomaly_flag": False,
                "anomaly_reason": None,
                "rover_lat": rover_lat,
                "rover_lon": rover_lon,
            }

            for rec in group:
                st = rec["sensor_type"]

                if st == "ATS":
                    # Read DN from raw object in MinIO
                    dn = _read_sensor_dn(rec, 1)
                    silver["temperature_ats_c"] = calibrate_ats(dn) if dn is not None else None
                    silver["has_ats"] = dn is not None
                elif st == "PS":
                    dn = _read_sensor_dn(rec, 1)
                    silver["pressure_hpa"] = calibrate_ps(dn) if dn is not None else None
                    silver["has_ps"] = dn is not None
                elif st == "WS":
                    dn_speed = _read_sensor_dn(rec, 1)
                    dn_dir = _read_sensor_dn(rec, 2)
                    silver["wind_speed_ms"] = calibrate_ws_speed(dn_speed) if dn_speed is not None else None
                    silver["wind_direction_deg"] = calibrate_ws_dir(dn_dir) if dn_dir is not None else None
                    silver["has_ws"] = dn_speed is not None
                elif st == "UV":
                    dn = _read_sensor_dn(rec, 1)
                    silver["uv_irradiance_w_m2"] = calibrate_uv(dn) if dn is not None else None
                    silver["has_uv"] = dn is not None
                elif st == "HS":
                    dn = _read_sensor_dn(rec, 1)
                    silver["humidity_pct"] = calibrate_hs(dn) if dn is not None else None
                    silver["has_hs"] = dn is not None

            silver_rows.append(silver)

        conn.close()
        log.info(f"Silver: calibrated {len(silver_rows)} (sol, sclk) groups")
        context["ti"].xcom_push(key="silver_rows", value=silver_rows)

    def _read_sensor_dn(rec: dict, dn_index: int) -> int | None:
        """Reads DN value from the raw MinIO object payload at uint16 position dn_index (1-based)."""
        try:
            client = _get_minio()
            obj = client.get_object(MEDA_BUCKET_RAW, rec["minio_raw_key"])
            raw_bytes = obj.read()
            payload_offset = CCSDS_PRIMARY_HDR_LEN + MEDA_SEC_HDR_LEN
            payload = raw_bytes[payload_offset:]
            offset = (dn_index - 1) * 2
            if len(payload) >= offset + 2:
                return struct.unpack_from(">H", payload, offset)[0]
        except Exception as e:
            log.warning(f"DN read failed for {rec.get('minio_raw_key')}: {e}")
        return None

    calibrate_task = PythonOperator(task_id="calibrate_silver", python_callable=calibrate_silver)

    # ── TASK 5: Write Silver MinIO ────────────────────────────
    def write_silver_minio(**context):
        """Serializa cada fila Silver a JSON y la escribe en MinIO meda-silver."""
        silver_rows = context["ti"].xcom_pull(key="silver_rows", task_ids="calibrate_silver")
        client = _get_minio()

        for row in silver_rows:
            key = f"{int(row['sol']):04d}/{row['sclk']:.3f}.json"
            body = json.dumps(row, default=str).encode()
            client.put_object(
                MEDA_BUCKET_SILVER, key,
                io.BytesIO(body), len(body),
                content_type="application/json",
            )

        log.info(f"Silver MinIO: wrote {len(silver_rows)} objects")

    write_silver_task = PythonOperator(task_id="write_silver_minio", python_callable=write_silver_minio)

    # ── TASK 6: Update Silver Postgres ───────────────────────
    def update_silver_postgres(**context):
        """Upsert science.meda_silver_readings con PostGIS (ON CONFLICT sol, sclk)."""
        silver_rows = context["ti"].xcom_pull(key="silver_rows", task_ids="calibrate_silver")
        conn = _get_pg()

        sql = """
            INSERT INTO science.meda_silver_readings
                (sol, sclk, lmst_h, temperature_ats_c, pressure_hpa, wind_speed_ms,
                 wind_direction_deg, uv_irradiance_w_m2, humidity_pct,
                 has_ats, has_ps, has_ws, has_uv, has_hs,
                 anomaly_flag, anomaly_reason, rover_location)
            VALUES
                (%(sol)s, %(sclk)s, %(lmst_h)s,
                 %(temperature_ats_c)s, %(pressure_hpa)s, %(wind_speed_ms)s,
                 %(wind_direction_deg)s, %(uv_irradiance_w_m2)s, %(humidity_pct)s,
                 %(has_ats)s, %(has_ps)s, %(has_ws)s, %(has_uv)s, %(has_hs)s,
                 %(anomaly_flag)s, %(anomaly_reason)s,
                 CASE WHEN %(rover_lon)s IS NOT NULL AND %(rover_lat)s IS NOT NULL
                      THEN ST_SetSRID(ST_MakePoint(%(rover_lon)s, %(rover_lat)s), 4326)
                      ELSE NULL END)
            ON CONFLICT (sol, sclk) DO UPDATE SET
                temperature_ats_c  = EXCLUDED.temperature_ats_c,
                pressure_hpa       = EXCLUDED.pressure_hpa,
                wind_speed_ms      = EXCLUDED.wind_speed_ms,
                wind_direction_deg = EXCLUDED.wind_direction_deg,
                uv_irradiance_w_m2 = EXCLUDED.uv_irradiance_w_m2,
                humidity_pct       = EXCLUDED.humidity_pct,
                has_ats = EXCLUDED.has_ats, has_ps = EXCLUDED.has_ps,
                has_ws  = EXCLUDED.has_ws,  has_uv = EXCLUDED.has_uv,
                has_hs  = EXCLUDED.has_hs,
                anomaly_flag    = EXCLUDED.anomaly_flag,
                anomaly_reason  = EXCLUDED.anomaly_reason,
                rover_location  = EXCLUDED.rover_location,
                updated_at      = NOW()
        """

        processed_sols = set()
        with conn.cursor() as cur:
            for row in silver_rows:
                cur.execute(sql, row)
                processed_sols.add(row["sol"])

        conn.commit()
        conn.close()
        log.info(f"Silver Postgres: upserted {len(silver_rows)} readings")
        context["ti"].xcom_push(key="processed_sols", value=list(processed_sols))

    silver_pg_task = PythonOperator(task_id="update_silver_postgres", python_callable=update_silver_postgres)

    # ── TASK 7: Detect Anomalies ──────────────────────────────
    def detect_anomalies_task(**context):
        """Aplica reglas de anomalía MEDA y actualiza anomaly_flag en Postgres."""
        silver_rows = context["ti"].xcom_pull(key="silver_rows", task_ids="calibrate_silver")
        conn = _get_pg()
        anomaly_count = 0

        with conn.cursor() as cur:
            for row in silver_rows:
                flag, reason = meda_detect_anomalies(row)
                cur.execute(
                    """
                    UPDATE science.meda_silver_readings
                    SET anomaly_flag = %s, anomaly_reason = %s
                    WHERE sol = %s AND sclk = %s
                    """,
                    (flag, reason, row["sol"], row["sclk"]),
                )
                if flag:
                    anomaly_count += 1

        conn.commit()
        conn.close()
        log.info(f"Anomaly detection: {anomaly_count}/{len(silver_rows)} flagged")
        context["ti"].xcom_push(key="anomaly_count", value=anomaly_count)

    anomaly_task = PythonOperator(task_id="detect_anomalies", python_callable=detect_anomalies_task)

    # ── TASK 8: Build Gold Aggregates ─────────────────────────
    def build_gold_aggregates(**context):
        """Agrega por sol y escribe JSON Gold en meda-gold para Grafana/dashboard.

        Coexistencia deliberada con dbt (ADR-001): este task escribe JSON para
        consumo inmediato por Grafana; dbt agrega los mismos datos de forma
        declarativa en fct_meda_sol_summary para análisis SQL.
        """
        processed_sols = context["ti"].xcom_pull(key="processed_sols", task_ids="update_silver_postgres")
        conn = _get_pg()
        client = _get_minio()

        sql = """
            SELECT
                sol,
                MIN(temperature_ats_c)   AS temp_min_c,
                MAX(temperature_ats_c)   AS temp_max_c,
                AVG(temperature_ats_c)   AS temp_avg_c,
                AVG(pressure_hpa)        AS pressure_avg_hpa,
                MAX(wind_speed_ms)       AS wind_speed_max_ms,
                AVG(uv_irradiance_w_m2) * 24.659 AS uv_dose_wh_m2,
                COUNT(*)                 AS reading_count,
                SUM(CASE WHEN anomaly_flag THEN 1 ELSE 0 END) AS anomaly_count
            FROM science.meda_silver_readings
            WHERE sol = %s
            GROUP BY sol
        """

        for sol in (processed_sols or []):
            with conn.cursor() as cur:
                cur.execute(sql, (sol,))
                row = cur.fetchone()
                if not row:
                    continue
                cols = [d[0] for d in cur.description]
                summary = dict(zip(cols, row))
                summary["generated_at"] = datetime.utcnow().isoformat()

            body = json.dumps(summary, default=str).encode()
            key = f"{int(sol):04d}/summary.json"
            client.put_object(
                MEDA_BUCKET_GOLD, key,
                io.BytesIO(body), len(body),
                content_type="application/json",
            )
            log.info(f"Gold aggregate: sol={sol} → {key}")

        conn.close()

    gold_task = PythonOperator(task_id="build_gold_aggregates", python_callable=build_gold_aggregates)

    # ── TASK 9: dbt build ─────────────────────────────────────
    dbt_build_task = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"dbt build --select fct_meda_sol_summary "
            f"--profiles-dir {DBT_PROFILES_DIR} --project-dir {DBT_PROJECT_DIR}"
        ),
    )

    # ── TASK 10: Commit Kafka offsets ─────────────────────────
    def commit_kafka_offsets(**context):
        """Comitea offsets de telemetry.meda.raw solo si todo lo anterior tuvo éxito (RF-009)."""
        offsets = context["ti"].xcom_pull(key="kafka_offsets", task_ids="poll_meda_queue")
        if not offsets:
            log.info("No offsets to commit")
            return 0

        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": MEDA_CONSUMER_GROUP,
            "enable.auto.commit": False,
        })
        tps = [TopicPartition(o["topic"], o["partition"], o["offset"]) for o in offsets]
        consumer.commit(offsets=tps, asynchronous=False)
        consumer.close()
        log.info(f"Kafka offsets committed: {len(tps)} partitions")
        return len(tps)

    commit_task = PythonOperator(task_id="commit_kafka_offsets", python_callable=commit_kafka_offsets)

    # ── TASK 11: Notify ───────────────────────────────────────
    def notify(**context):
        """Log métricas de completitud del pipeline MEDA."""
        raw_messages = context["ti"].xcom_pull(key="raw_messages", task_ids="poll_meda_queue") or []
        anomaly_count = context["ti"].xcom_pull(key="anomaly_count", task_ids="detect_anomalies") or 0
        processed_sols = context["ti"].xcom_pull(key="processed_sols", task_ids="update_silver_postgres") or []
        log.info(
            f"MEDA pipeline complete | batch_size={len(raw_messages)} | "
            f"sols_processed={processed_sols} | anomalies={anomaly_count} | "
            f"offsets_committed=True | pipeline=meda_full_pipeline"
        )
        return {
            "batch_size": len(raw_messages),
            "processed_sols": processed_sols,
            "anomaly_count": anomaly_count,
        }

    notify_task = PythonOperator(task_id="notify", python_callable=notify)

    # ── Wire tasks ────────────────────────────────────────────
    (
        poll_task
        >> ingest_task
        >> validate_task
        >> calibrate_task
        >> write_silver_task
        >> silver_pg_task
        >> anomaly_task
        >> gold_task
        >> dbt_build_task
        >> commit_task
        >> notify_task
    )
