"""
Airflow DAG — Mastcam-Z Full ETL Pipeline
Orchestrates the complete data lifecycle from Raw DSN data to Gold analytical layer.

Pipeline stages (Medallion Architecture):
  RAW    → Direct from DSN/Kafka (MinIO mastcamz-raw)
  BRONZE → Validated, catalogued, no transformation (MinIO mastcamz-bronze)
  SILVER → Calibrated images, enriched metadata, PostgreSQL indexed
  GOLD   → Aggregated, analysis-ready, Grafana-ready

Schedule:
  Every 15 minutes (simulates ~1 MRO pass per sol compressed to 15 min intervals)

Tasks:
   1. poll_bronze_queue        — Poll Kafka etl.bronze.ready topic (NO comitea offsets todavía)
   2. validate_raw_products    — CRC check, completeness, PDS4 label parse
   3. radiometric_calibration  — Apply flat-field, dark, photometric correction
   4. geometric_calibration    — Camera model, pointing, map projection
   5. write_silver_layer       — Store calibrated TIFF + enriched JSON to MinIO/S3 silver
   6. update_postgis           — Upsert geospatial record with rover footprint (idempotente, ON CONFLICT)
   7. anomaly_detection        — Flag dust storms, sensor outliers (umbrales parametrizables)
   8. build_gold_aggregates    — Sol stats a una key estable (idempotente, se sobrescribe)
   9. dbt_build                — Modelos staging + marts sobre Postgres, con tests
  10. commit_kafka_offsets     — Comitea los offsets de Kafka SOLO si 8 y 9 tuvieron éxito
  11. notify_science_team      — Log pipeline completion metrics

Nota de robustez (ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7):
los writes a Silver/Bronze (keys deterministas) y a Postgres (upsert ON CONFLICT)
son idempotentes, y el commit de Kafka se difiere al final — así que si el DAG
falla a mitad de camino y Airflow reintenta, reprocesar el mismo lote de mensajes
es seguro (at-least-once + writes idempotentes = efecto exactly-once).
"""

import io
import json
import logging
import os
from datetime import datetime, timedelta

from airflow.decorators import task
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from anomaly_rules import classify_severity, detect_anomalies
from calibration import (
    BIAS_DN,
    DARK_RATE_DN_S,
    e_sun_for_wavelength,
    ground_sample_distance_mm,
    radiometric_factor,
    stereo_camera_offset_m,
)
from kafka_offsets import offsets_to_commit_list, track_max_offset

from airflow import DAG

log = logging.getLogger(__name__)

# ── DAG defaults ────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "data_engineering",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
    "execution_timeout": timedelta(minutes=30),
}

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").replace("http://", "").replace("https://", "")
MINIO_SECURE  = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin")
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")
KAFKA_BOOTSTRAP= os.getenv("KAFKA_BOOTSTRAP",  "kafka:9092")
POSTGRES_CONN  = os.getenv("POSTGRES_CONN",    "postgresql://rover:rover2024@postgres:5432/rover_mars")
DBT_PROJECT_DIR = os.getenv("DBT_PROJECT_DIR", "/opt/airflow/dbt")
DBT_PROFILES_DIR = os.getenv("DBT_PROFILES_DIR", "/opt/airflow/dbt")

# Nombres de bucket configurables: por defecto los del MinIO local
# (docker-compose.yml); en AWS apuntan a los buckets reales creados por
# infra/aws/s3.tf (ADR-012), p.ej. rovermars-raw-demo.
S3_BUCKET_RAW    = os.getenv("S3_BUCKET_RAW",    "mastcamz-raw")
S3_BUCKET_PDS4   = os.getenv("S3_BUCKET_PDS4",   "mastcamz-pds4")
S3_BUCKET_SILVER = os.getenv("S3_BUCKET_SILVER", "mastcamz-silver")
S3_BUCKET_GOLD   = os.getenv("S3_BUCKET_GOLD",   "mastcamz-gold")

# Key estable (NO timestamped) para el snapshot Gold agregado — ver
# build_gold_aggregates más abajo y Fase 7 de la guía de implementación:
# una key con timestamp rompía la idempotencia (cada corrida creaba un objeto
# nuevo en vez de actualizar el snapshot vigente).
GOLD_SUMMARY_KEY = os.getenv("GOLD_SUMMARY_KEY", "aggregates/gold_sol_summary.json")

# Parámetros del consumidor Kafka (antes hardcodeados inline en poll_bronze_queue).
KAFKA_CONSUMER_GROUP    = os.getenv("KAFKA_CONSUMER_GROUP", "airflow_etl_consumer")
KAFKA_POLL_TIMEOUT_S    = float(os.getenv("KAFKA_POLL_TIMEOUT_S", "20"))
KAFKA_POLL_MAX_MESSAGES = int(os.getenv("KAFKA_POLL_MAX_MESSAGES", "50"))


def get_minio():
    # MINIO_SECURE=false + endpoint tipo host:puerto -> MinIO local (docker-compose.yml)
    # MINIO_SECURE=true  + endpoint s3.amazonaws.com -> AWS S3 real (infra/aws, ver ADR-012)
    # Construcción del cliente centralizada en common/ — ver
    # docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7.
    from rovermars_common.storage import build_object_store_client
    return build_object_store_client(
        endpoint=MINIO_ENDPOINT, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET,
        secure=MINIO_SECURE, region=AWS_REGION,
    )


def get_pg():
    import psycopg2
    return psycopg2.connect(POSTGRES_CONN)


# ═══════════════════════════════════════════════════════════
# DAG Definition
# ═══════════════════════════════════════════════════════════
with DAG(
    dag_id="mastcamz_full_pipeline",
    description="Mastcam-Z ETL: Raw DSN → Bronze → Silver → Gold (Medallion Architecture)",
    schedule_interval="*/15 * * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=3,
    default_args=DEFAULT_ARGS,
    tags=["mars", "mastcamz", "perseverance", "etl", "nasa"],
    doc_md="""
    ## Mastcam-Z Full ETL Pipeline

    Simulates NASA's Multi-mission Image Processing Laboratory (MIPL) pipeline
    for processing Mastcam-Z images from raw DSN delivery to science-ready products.

    ### Data flow
    ```
    Kafka:etl.bronze.ready → validate → calibrate → silver → postgis → gold
    ```

    ### Calibration steps (per NASA/MIPL)
    1. **Bias subtraction** — Remove CCD bias offset (~2000 DN)
    2. **Dark current** — Subtract thermally-generated signal
    3. **Flat-field** — Correct pixel-to-pixel sensitivity variation
    4. **Radiometric** — Convert DN → radiance (W/m²/sr/nm) or I/F
    5. **Geometric** — Apply CAHVOR camera model, co-register stereo pair
    """,
) as dag:

    start = EmptyOperator(task_id="start_pipeline")
    end   = EmptyOperator(task_id="end_pipeline")

    # ── TASK 1: Poll Kafka for new Bronze-ready products ────
    @task(task_id="poll_bronze_queue", multiple_outputs=True)
    def poll_bronze_queue(**context) -> dict:
        """
        Consume hasta KAFKA_POLL_MAX_MESSAGES eventos de etl.bronze.ready.

        A propósito, NO comitea los offsets aquí (enable.auto.commit=False y sin
        `consumer.commit()` por mensaje, a diferencia de antes). El commit real lo
        hace la tarea `commit_kafka_offsets`, al final del DAG, solo si Silver,
        Postgres y dbt tuvieron éxito — así un fallo a mitad de pipeline no pierde
        mensajes: el próximo intento los vuelve a leer (los writes downstream son
        idempotentes, así que reprocesar es seguro). Ver Fase 7 de la guía.
        """
        from confluent_kafka import Consumer, KafkaError

        consumer = Consumer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id":          KAFKA_CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "max.poll.interval.ms": 60000,
        })
        consumer.subscribe(["etl.bronze.ready"])

        products = []
        offsets: dict = {}
        start_t = __import__("time").time()

        while (
            __import__("time").time() - start_t < KAFKA_POLL_TIMEOUT_S
            and len(products) < KAFKA_POLL_MAX_MESSAGES
        ):
            msg = consumer.poll(timeout=2.0)
            if msg is None:
                break
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.warning(f"Kafka error: {msg.error()}")
                continue
            try:
                products.append(json.loads(msg.value().decode()))
                track_max_offset(offsets, msg.topic(), msg.partition(), msg.offset())
            except Exception as e:
                log.warning(f"Parse error: {e}")

        consumer.close()
        log.info(f"Polled {len(products)} products from bronze queue (sin comitear todavía)")
        return {"products": products, "kafka_offsets": offsets_to_commit_list(offsets)}

    # ── TASK 2: Validate raw products ──────────────────────
    @task(task_id="validate_raw_products")
    def validate_raw_products(products: list[dict]) -> list[dict]:
        """
        Validate each bronze product:
        - Check MinIO object exists
        - Parse PDS4 XML label
        - Verify image dimensions
        - Flag quality issues
        """
        client = get_minio()
        valid  = []

        for p in products:
            try:
                # Check raw IMG object in MinIO
                raw_key = p.get("minio_raw_key", "")
                if raw_key:
                    stat = client.stat_object(S3_BUCKET_RAW, raw_key)
                    p["raw_size_bytes"] = stat.size

                # Check PDS4 XML label
                xml_key = raw_key.replace(".IMG", ".xml")
                try:
                    xml_obj = client.get_object(S3_BUCKET_PDS4, xml_key)
                    xml_content = xml_obj.read()
                    p["pds4_label_size"] = len(xml_content)
                    p["pds4_valid"] = b"Product_Observational" in xml_content
                except Exception:
                    p["pds4_valid"] = False

                p["validation_status"] = "VALID" if p.get("pds4_valid", False) else "WARN_NO_LABEL"
                p["validated_at"] = datetime.utcnow().isoformat()
                valid.append(p)

            except Exception as e:
                log.warning(f"Product {p.get('product_id', '?')} failed validation: {e}")
                p["validation_status"] = "INVALID"
                p["validation_error"]  = str(e)

        log.info(f"Validated {len(valid)}/{len(products)} products")
        return valid

    # ── TASK 3: Radiometric calibration ────────────────────
    @task(task_id="radiometric_calibration")
    def radiometric_calibration(products: list[dict]) -> list[dict]:
        """
        Apply radiometric calibration chain (simplified NASA/MIPL pipeline):
          1. Bias subtraction (CCD offset ~2000 DN)
          2. Dark current correction (T-dependent model)
          3. Flat-field correction (per-filter response map)
          4. Absolute radiometric conversion: DN → I/F (irradiance factor)

        I/F = (π × L) / (E_sun × cos(θ_sun))
        where:
          L    = radiance (W/m²/sr/nm)
          E_sun= solar irradiance at Mars (W/m²/nm)
          θ_sun= solar incidence angle
        """
        calibrated = []

        for p in products:
            if p.get("validation_status") == "INVALID":
                continue

            wl = p.get("filter_wavelength_nm", 530)

            # Matemática de calibración extraída y testeada en airflow/plugins/calibration.py
            # (ver tests/test_calibration.py)
            p["calibration"] = {
                "bias_dn":          BIAS_DN,
                "dark_rate_dn_s":   DARK_RATE_DN_S,
                "e_sun_mars_wm2nm": e_sun_for_wavelength(wl),
                "radiometric_factor": radiometric_factor(wl),
                "calibration_version": "RDR_v1.0",
                "flatfield_applied": True,
                "dark_corrected":    True,
                "calibrated_at":     datetime.utcnow().isoformat(),
            }
            p["processing_stage"] = "SILVER_CALIBRATING"
            calibrated.append(p)

        log.info(f"Radiometric calibration applied to {len(calibrated)} products")
        return calibrated

    # ── TASK 4: Geometric calibration ──────────────────────
    @task(task_id="geometric_calibration")
    def geometric_calibration(products: list[dict]) -> list[dict]:
        """
        Apply geometric calibration using CAHVOR camera model:
          - C: Camera center position
          - A: Optical axis unit vector
          - H: Horizontal reference vector
          - V: Vertical reference vector
          - O: Optical axis (true, with distortion)
          - R: Radial distortion coefficients

        For stereo pairs, compute:
          - Baseline: 24.3 cm (ZL to ZR separation)
          - Disparity map
          - 3D point cloud of Mars surface
        """
        geometrized = []

        for p in products:
            eye   = p.get("camera_eye", "LEFT")
            focal = p.get("focal_mm", 26.0)
            lat   = p.get("rover_latitude_deg",  18.4447)
            lon   = p.get("rover_longitude_deg", 77.4508)

            # CAHVOR model parameters (simplified). Offset Y del centro de cámara
            # y GSD calculados en airflow/plugins/calibration.py (testeados en
            # tests/test_calibration.py).
            cahvor = {
                "C": [0.0, stereo_camera_offset_m(eye), 2.1],
                "A": [0.0, 0.0, 1.0],
                "H": [focal / 0.0074, 0.0, 823.5],
                "V": [0.0, focal / 0.0074, 607.5],
                "O": [0.0, 0.0, 1.0],
                "R": [0.0, 0.0, 0.0],
            }

            # Ground sample distance at 10 m range (10000 mm)
            gsd_mm_10m = ground_sample_distance_mm(range_mm=10000, focal_mm=focal)

            p["geometry"] = {
                "cahvor_model": cahvor,
                "gsd_mm_at_10m": gsd_mm_10m,
                "stereo_baseline_cm": 24.3 if eye == "LEFT" else 0.0,
                "map_projected": False,
                "coordinate_system": "ROVER_FRAME",
                "rover_lat": lat,
                "rover_lon": lon,
                "geometric_calibration_at": datetime.utcnow().isoformat(),
            }
            geometrized.append(p)

        log.info(f"Geometric calibration done for {len(geometrized)} products")
        return geometrized

    # ── TASK 5: Write Silver ────────────────────────────────
    @task(task_id="write_silver_layer")
    def write_silver_layer(products: list[dict]) -> list[dict]:
        """
        Write calibrated products to MinIO Silver bucket.
        Each product gets:
          - calibrated metadata JSON (Silver record)
          - Updated MinIO key
        """
        client = get_minio()
        silver_products = []

        for p in products:
            sol      = p.get("sol", 0)
            filename = p.get("file_name", "unknown.IMG")
            silver_key = f"sol={sol:04d}/{filename.replace('.IMG', '')}_SILVER.json"

            p["processing_stage"] = "SILVER"
            p["silver_key"]       = silver_key
            p["silver_written_at"]= datetime.utcnow().isoformat()

            body = json.dumps(p, indent=2, default=str).encode()
            client.put_object(
                S3_BUCKET_SILVER,
                silver_key,
                io.BytesIO(body),
                len(body),
                content_type="application/json",
            )
            silver_products.append(p)
            log.info(f"Silver: sol={sol:04d} {filename} → {silver_key}")

        return silver_products

    # ── TASK 6: Update PostGIS ──────────────────────────────
    @task(task_id="update_postgis")
    def update_postgis(products: list[dict]) -> int:
        """
        Upsert image footprints and calibrated metadata into PostgreSQL/PostGIS.
        Creates geospatial camera footprint polygon (simplified point-to-footprint).
        """
        conn = get_pg()

        sql_upsert = """
            INSERT INTO image_products (
                product_id, file_name, sol, sclk, camera_eye,
                filter_wavelength_nm, focal_mm, dsn_station,
                light_delay_s, capture_utc, arrival_utc,
                product_type, processing_stage, quality_flag,
                minio_bronze_key, minio_silver_key,
                rover_location, horizontal_fov_deg, vertical_fov_deg
            ) VALUES (
                %(product_id)s, %(file_name)s, %(sol)s, %(sclk)s, %(camera_eye)s,
                %(filter_wavelength_nm)s, %(focal_mm)s, %(dsn_station)s,
                %(light_delay_s)s, %(capture_utc)s::timestamptz,
                %(arrival_utc)s::timestamptz,
                %(product_type)s, 'SILVER', %(quality_flag)s,
                %(minio_raw_key)s, %(silver_key)s,
                ST_SetSRID(ST_MakePoint(%(rover_lon)s, %(rover_lat)s), 4326),
                %(h_fov)s, %(v_fov)s
            )
            ON CONFLICT (product_id) DO UPDATE SET
                processing_stage = EXCLUDED.processing_stage,
                minio_silver_key = EXCLUDED.minio_silver_key,
                rover_location   = EXCLUDED.rover_location;
        """

        count = 0
        with conn.cursor() as cur:
            for p in products:
                geo = p.get("geometry", {})
                params = {
                    **p,
                    "rover_lat": geo.get("rover_lat", 18.4447),
                    "rover_lon": geo.get("rover_lon", 77.4508),
                    "h_fov": p.get("calibration", {}).get("horizontal_fov", 25.6),
                    "v_fov": p.get("calibration", {}).get("vertical_fov",   19.2),
                    "capture_utc": p.get("capture_utc", "2024-01-01T00:00:00Z"),
                    "arrival_utc": p.get("arrival_utc", "2024-01-01T00:00:00Z"),
                }
                try:
                    cur.execute(sql_upsert, params)
                    count += 1
                except Exception as e:
                    log.warning(f"PostGIS upsert failed for {p.get('product_id')}: {e}")
                    conn.rollback()

        conn.commit()
        conn.close()
        log.info(f"PostGIS: updated {count} image footprints")
        return count

    # ── TASK 7: Anomaly detection ───────────────────────────
    @task(task_id="anomaly_detection")
    def anomaly_detection(products: list[dict]) -> list[dict]:
        """
        Flag anomalies in sensor and image data (dust storms, low battery).

        La regla en sí (`detect_anomalies`/`classify_severity`) vive en
        airflow/plugins/anomaly_rules.py — separada de esta tarea para poder
        testearla sin Kafka/Postgres, y con los umbrales parametrizables por
        entorno (DUST_STORM_TAU_THRESHOLD, LOW_BATTERY_PCT_THRESHOLD) en vez de
        hardcodeados. Ver tests/test_anomaly_rules.py y Fase 7 de la guía.
        """
        alerts = []

        for p in products:
            issues = detect_anomalies(p)

            if issues:
                alerts.append({
                    "product_id": p.get("product_id"),
                    "sol":        p.get("sol"),
                    "alerts":     issues,
                    "severity":   classify_severity(issues),
                    "detected_at": datetime.utcnow().isoformat(),
                })
                log.warning(f"ANOMALY Sol {p.get('sol'):04d}: {issues}")

        if alerts:
            # En AWS: publicar a SNS (ver ADR-016) — pendiente, documentado como
            # próximo paso en la Fase 6/7 de la guía de implementación.
            log.info(f"Anomaly detection: {len(alerts)} alerts generated")

        return alerts

    # ── TASK 8: Build Gold aggregates ──────────────────────
    @task(task_id="build_gold_aggregates")
    def build_gold_aggregates(**context) -> dict:
        """
        Build Gold layer aggregates from Silver data:
          - Daily/sol statistics per filter
          - Rover traverse path GeoJSON
          - Multispectral composite summary
          - Telemetry time-series summary (for Grafana)
        """
        conn = get_pg()
        client = get_minio()

        sql_stats = """
            SELECT
                sol,
                camera_eye,
                filter_wavelength_nm,
                COUNT(*)                          AS n_images,
                AVG(focal_mm)                     AS avg_focal_mm,
                MIN(arrival_utc)                  AS first_arrival,
                MAX(arrival_utc)                  AS last_arrival
            FROM image_products
            WHERE processing_stage = 'SILVER'
              AND sol = (SELECT MAX(sol) FROM image_products)
            GROUP BY sol, camera_eye, filter_wavelength_nm
            ORDER BY sol, camera_eye, filter_wavelength_nm;
        """

        sql_path = """
            SELECT sol,
                   ST_AsGeoJSON(rover_location)::json AS position
            FROM image_products
            WHERE rover_location IS NOT NULL
            ORDER BY sol;
        """

        gold_record = {
            "generated_at": datetime.utcnow().isoformat(),
            "pipeline_version": "1.0.0",
            "filter_stats": [],
            "rover_traverse_geojson": {"type": "LineString", "coordinates": []},
        }

        try:
            with conn.cursor() as cur:
                cur.execute(sql_stats)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                gold_record["filter_stats"] = [dict(zip(cols, r)) for r in rows]

                cur.execute(sql_path)
                for row in cur.fetchall():
                    pos = row[1]
                    if pos and "coordinates" in pos:
                        gold_record["rover_traverse_geojson"]["coordinates"].append(
                            pos["coordinates"]
                        )

        except Exception as e:
            log.warning(f"Gold aggregation query failed: {e}")
        finally:
            conn.close()

        body = json.dumps(gold_record, indent=2, default=str).encode()
        # Key ESTABLE (antes tenía un timestamp en el nombre): dado el mismo estado
        # de Postgres, esta tarea siempre produce el mismo `gold_record`, así que
        # debe sobrescribir el mismo objeto en vez de acumular uno nuevo por corrida
        # — de lo contrario nunca es idempotente y el bucket crece sin límite. El
        # histórico, si se necesita, lo da gratis el versionado de S3 ya habilitado
        # en infra/aws/s3.tf (ADR-012), sin sacrificar la idempotencia de esta key.
        client.put_object(
            S3_BUCKET_GOLD, GOLD_SUMMARY_KEY,
            io.BytesIO(body), len(body),
            content_type="application/json",
        )
        log.info(f"Gold aggregate written: {GOLD_SUMMARY_KEY}")
        return gold_record

    # ── TASK 9: dbt build (staging + marts sobre el esquema Postgres) ──
    # ADR-001 (docs/ANALISIS_MODERN_DATA_STACK.md): la agregación Silver->Gold
    # se traslada progresivamente a SQL declarativo y testeable con dbt, en
    # paralelo a build_gold_aggregates (que sigue escribiendo el JSON de Gold
    # en MinIO/S3 que ya consumen Grafana y el dashboard).
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            # dbt deps instala dbt_utils (dbt/packages.yml) — sin esto, dbt build
            # fallaba al parsear dbt/models/marts/_marts__models.yml (bug real
            # encontrado en despliegue, ver docs/DESPLIEGUE_MINIPC.md).
            f"dbt deps --profiles-dir {DBT_PROFILES_DIR} --project-dir {DBT_PROJECT_DIR} && "
            f"dbt build --profiles-dir {DBT_PROFILES_DIR} --project-dir {DBT_PROJECT_DIR}"
        ),
    )

    # ── TASK 10: Commit Kafka offsets (solo si todo lo anterior tuvo éxito) ──
    @task(task_id="commit_kafka_offsets")
    def commit_kafka_offsets(offsets: list[dict]) -> int:
        """
        Confirma (commit) los offsets de `etl.bronze.ready` leídos por
        poll_bronze_queue. Se ejecuta al final, downstream de build_gold_aggregates
        y dbt_build (ver wiring): si cualquiera de las tareas intermedias falla,
        Airflow reintenta el DAG SIN haber comiteado, y el próximo
        poll_bronze_queue vuelve a leer los mismos mensajes desde Kafka — seguro
        porque todos los writes downstream son idempotentes (keys deterministas +
        upsert `ON CONFLICT`). Ver Fase 7 de la guía de implementación.
        """
        if not offsets:
            log.info("Sin offsets que comitear (no llegaron mensajes en este batch)")
            return 0

        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id":          KAFKA_CONSUMER_GROUP,
            "enable.auto.commit": False,
        })
        tps = [TopicPartition(o["topic"], o["partition"], o["offset"]) for o in offsets]
        consumer.commit(offsets=tps, asynchronous=False)
        consumer.close()
        log.info(f"Kafka offsets comiteados: {tps}")
        return len(tps)

    # ── TASK 11: Notify science team ─────────────────────────
    @task(task_id="notify_science_team")
    def notify_science_team(gold_data: dict, n_postgis: int, alerts: list, n_offsets_committed: int) -> None:
        """Log pipeline completion metrics (replace with email/Slack in production)."""
        n_filters = len(gold_data.get("filter_stats", []))
        n_coords  = len(gold_data.get("rover_traverse_geojson", {}).get("coordinates", []))
        log.info(
            f"Pipeline complete | "
            f"filter_stats={n_filters} | "
            f"postgis_updated={n_postgis} | "
            f"traverse_points={n_coords} | "
            f"alerts={len(alerts)} | "
            f"kafka_partitions_committed={n_offsets_committed}"
        )

    # ── Wire tasks ──────────────────────────────────────────
    polled              = poll_bronze_queue()
    products_raw        = polled["products"]
    kafka_offsets       = polled["kafka_offsets"]
    products_validated  = validate_raw_products(products_raw)
    products_radio      = radiometric_calibration(products_validated)
    products_geo        = geometric_calibration(products_radio)
    products_silver     = write_silver_layer(products_geo)
    n_postgis           = update_postgis(products_silver)
    alerts              = anomaly_detection(products_silver)
    gold                = build_gold_aggregates()
    commit_offsets      = commit_kafka_offsets(kafka_offsets)
    notify              = notify_science_team(gold, n_postgis, alerts, commit_offsets)

    (
        start
        >> polled
        >> products_validated
        >> products_radio
        >> products_geo
        >> products_silver
        >> [n_postgis, alerts]
        >> gold
    )
    n_postgis >> dbt_build
    # commit_kafka_offsets depende explícitamente de gold Y dbt_build: solo se
    # comitea cuando toda la ruta crítica (Silver->Postgres->dbt->Gold) ya escribió
    # con éxito. Ver docstring de la tarea y Fase 7 de la guía.
    [gold, dbt_build] >> commit_offsets >> notify >> end
