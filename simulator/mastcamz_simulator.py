"""
Mastcam-Z Simulator — Mars 2020 Perseverance Rover
Simulates image capture, PDS4 metadata generation, and CCSDS packet encoding.

Technical basis:
  - CCD: 1648 × 1214 pixels, 7.4 µm/pixel
  - Zoom: 26–110 mm focal length (4:1)
  - 8-position filter wheel (400–1012 nm)
  - Stereo pair: Left (ZL) + Right (ZR) cameras
  - Data format: PDS4 IMG + XML label
  - Compression: ICER (lossy) or lossless
  - APID 0x01A5 (Mastcam-Z Left), 0x01A6 (Mastcam-Z Right)

Reference: Bell et al. 2021, Space Science Reviews 217:24
"""

import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
from ccsds_encoder import CCSDSEncoder, SpacecraftPacket
from telemetry_generator import MarsEnvironment, RoverTelemetry

# ── Mastcam-Z filter wheel definitions ─────────────────────────────────────
FILTERS_LEFT = {
    0: {"name": "L0-Broadband", "wavelength_nm": 530, "bandwidth_nm": 300, "type": "RGB"},
    1: {"name": "L1-Blue",     "wavelength_nm": 445, "bandwidth_nm": 22,  "type": "narrowband"},
    2: {"name": "L2-Green",    "wavelength_nm": 527, "bandwidth_nm": 22,  "type": "narrowband"},
    3: {"name": "L3-Red",      "wavelength_nm": 676, "bandwidth_nm": 22,  "type": "narrowband"},
    4: {"name": "L4-NIR-800",  "wavelength_nm": 800, "bandwidth_nm": 22,  "type": "narrowband"},
    5: {"name": "L5-NIR-866",  "wavelength_nm": 866, "bandwidth_nm": 22,  "type": "narrowband"},
    6: {"name": "L6-NIR-910",  "wavelength_nm": 910, "bandwidth_nm": 22,  "type": "narrowband"},
    7: {"name": "L7-NIR-939",  "wavelength_nm": 939, "bandwidth_nm": 22,  "type": "narrowband"},
}

FILTERS_RIGHT = {
    0: {"name": "R0-Broadband", "wavelength_nm": 530, "bandwidth_nm": 300, "type": "RGB"},
    1: {"name": "R1-NIR-480",  "wavelength_nm": 480, "bandwidth_nm": 22,  "type": "narrowband"},
    2: {"name": "R2-Green",    "wavelength_nm": 530, "bandwidth_nm": 22,  "type": "narrowband"},
    3: {"name": "R3-Red",      "wavelength_nm": 630, "bandwidth_nm": 22,  "type": "narrowband"},
    4: {"name": "R4-NIR-800",  "wavelength_nm": 800, "bandwidth_nm": 22,  "type": "narrowband"},
    5: {"name": "R5-NIR-908",  "wavelength_nm": 908, "bandwidth_nm": 22,  "type": "narrowband"},
    6: {"name": "R6-NIR-937",  "wavelength_nm": 937, "bandwidth_nm": 22,  "type": "narrowband"},
    7: {"name": "R7-NIR-1012", "wavelength_nm": 1012,"bandwidth_nm": 22,  "type": "narrowband"},
}

# Jezero Crater landing ellipse center (Mars planetocentric coordinates).
# Parametrizable por entorno para que coincida con telemetry_generator.py.
JEZERO_LAT_DEG = float(os.getenv("JEZERO_LAT", "18.4447"))
JEZERO_LON_DEG = float(os.getenv("JEZERO_LON", "77.4508"))
MARS_RADIUS_KM = 3389.5


@dataclass
class ImageCaptureParams:
    camera_eye: str              # "LEFT" | "RIGHT"
    filter_position: int         # 0–7
    focal_length_mm: float       # 26–110
    exposure_ms: float           # 1–500
    subframe_x1: int = 0
    subframe_y1: int = 0
    subframe_x2: int = 1648
    subframe_y2: int = 1214
    compression: str = "ICER"    # ICER | LOSSLESS | JPEG
    compression_quality: int = 85


@dataclass
class PDS4Metadata:
    """Simplified PDS4 label metadata for a Mastcam-Z image."""
    logical_identifier: str
    version_id: str = "1.0"
    title: str = ""
    mission_name: str = "Mars 2020"
    spacecraft_name: str = "Perseverance"
    instrument_id: str = "MASTCAM-Z"
    sol: int = 0
    start_date_time: str = ""
    stop_date_time: str = ""
    exposure_duration_ms: float = 0.0
    filter_name: str = ""
    filter_wavelength_nm: int = 0
    focal_length_mm: float = 0.0
    camera_eye: str = ""
    lines: int = 1214
    line_samples: int = 1648
    sample_bits: int = 12
    sample_bit_mask: str = "2#0000111111111111#"
    horizontal_fov_deg: float = 0.0
    vertical_fov_deg: float = 0.0
    pixel_scale_mrad_per_px: float = 0.0
    rover_latitude_deg: float = 0.0
    rover_longitude_deg: float = 0.0
    rover_altitude_m: float = 0.0
    surface_temperature_c: float = 0.0
    atm_pressure_pa: float = 0.0
    rover_battery_pct: float = 0.0
    rtt_seconds: float = 0.0         # Round-trip light time
    sclk_start: float = 0.0          # Spacecraft Clock start
    processing_level: str = "Raw"
    product_type: str = "IMAGE_EDR"
    file_name: str = ""
    checksum_md5: str = ""


class MastcamZCamera:
    """
    Simulates a single Mastcam-Z camera (left or right).
    Generates synthetic Mars imagery with accurate physical parameters.
    """

    FULL_FRAME_W = 1648
    FULL_FRAME_H = 1214
    PIXEL_SIZE_UM = 7.4

    # FOV lookup by focal length
    _FOV_TABLE = {
        26:  (25.6, 19.2),
        34:  (19.5, 14.7),
        48:  (13.9, 10.5),
        63:  (10.6, 8.0),
        79:  (8.5,  6.4),
        100: (6.7,  5.1),
        110: (6.2,  4.6),
    }

    def __init__(self, eye: str = "LEFT"):
        assert eye in ("LEFT", "RIGHT")
        self.eye = eye
        self.filters = FILTERS_LEFT if eye == "LEFT" else FILTERS_RIGHT
        self.apid = 0x01A5 if eye == "LEFT" else 0x01A6
        self.encoder = CCSDSEncoder(apid=self.apid)
        self._frame_counter = 0

    def _compute_fov(self, focal_mm: float) -> tuple[float, float]:
        """Compute horizontal and vertical FOV in degrees."""
        fov_h = 2 * math.degrees(math.atan(
            (self.FULL_FRAME_W * self.PIXEL_SIZE_UM * 1e-3) / (2 * focal_mm)
        ))
        fov_v = 2 * math.degrees(math.atan(
            (self.FULL_FRAME_H * self.PIXEL_SIZE_UM * 1e-3) / (2 * focal_mm)
        ))
        return fov_h, fov_v

    def _generate_synthetic_mars_image(
        self,
        params: ImageCaptureParams,
        telemetry: RoverTelemetry,
        sol: int,
    ) -> np.ndarray:
        """
        Generate a synthetic Mars landscape image with correct color science
        per the active filter. Returns uint16 array (12-bit data, left-aligned).
        """
        w = params.subframe_x2 - params.subframe_x1
        h = params.subframe_y2 - params.subframe_y1
        filt = self.filters[params.filter_position]
        wl = filt["wavelength_nm"]

        rng = np.random.default_rng(seed=sol * 1000 + params.filter_position)

        # Base terrain (Jezero crater floor)
        noise = rng.standard_normal((h, w, 3))
        gradient_v = np.linspace(0.3, 0.85, h)[:, None, None] * np.ones((1, w, 3))
        terrain = np.clip(gradient_v + noise * 0.06, 0, 1)

        # Mars reddish basalt color modulated by filter wavelength
        if wl < 500:          # Blue/UV – dust absorbs strongly
            color_bias = np.array([0.35, 0.30, 0.45])
        elif wl < 600:        # Green
            color_bias = np.array([0.50, 0.55, 0.35])
        elif wl < 750:        # Red
            color_bias = np.array([0.72, 0.45, 0.30])
        elif wl < 900:        # NIR – rocks brighter
            color_bias = np.array([0.65, 0.62, 0.60])
        else:                 # SWIR – mineral signatures
            color_bias = np.array([0.55, 0.58, 0.52])

        img_float = terrain * color_bias[None, None, :]

        # Add rocks (random dark ellipses)
        n_rocks = rng.integers(5, 25)
        for _ in range(n_rocks):
            cx = int(rng.integers(0, w))
            cy = int(rng.integers(int(h * 0.4), h))
            rx = int(rng.integers(3, min(30, w // 10)))
            ry = int(rng.integers(2, max(3, rx // 2)))
            rock_brightness = rng.uniform(0.15, 0.55)
            yy, xx = np.ogrid[:h, :w]
            mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1
            img_float[mask] = rock_brightness * color_bias

        # Sky horizon (upper 30%)
        sky_h = int(h * 0.30)
        sky_color = np.array([0.62, 0.52, 0.42])  # Mars dusty sky
        sky_alpha = np.linspace(0.9, 0.1, sky_h)[:, None, None]
        img_float[:sky_h] = (
            img_float[:sky_h] * (1 - sky_alpha) + sky_color[None, None, :] * sky_alpha
        )

        # Atmospheric haze
        haze = np.clip(rng.normal(0, 0.01, (h, w, 3)), -0.02, 0.02)
        img_float = np.clip(img_float + haze, 0, 1)

        # Apply exposure simulation
        exposure_factor = np.clip(params.exposure_ms / 50.0, 0.2, 4.0)
        img_float = np.clip(img_float * exposure_factor, 0, 1)

        # Convert to 12-bit (stored in uint16, left-aligned → shift 4 bits)
        img_12bit = (img_float * 4095).astype(np.uint16)

        # Broadband filter produces 3-channel, narrowband is single-channel
        if filt["type"] == "narrowband":
            # Use luminance of the colored image
            luminance = (img_12bit[:, :, 0] * 0.299 +
                         img_12bit[:, :, 1] * 0.587 +
                         img_12bit[:, :, 2] * 0.114).astype(np.uint16)
            return luminance[:, :, np.newaxis]

        return img_12bit

    def capture(
        self,
        params: ImageCaptureParams,
        telemetry: RoverTelemetry,
        sol: int,
        sclk: float,
    ) -> tuple[np.ndarray, PDS4Metadata]:
        """
        Simulate a full image capture event.
        Returns (image_array, pds4_metadata).
        """
        self._frame_counter += 1
        filt = self.filters[params.filter_position]
        fov_h, fov_v = self._compute_fov(params.focal_length_mm)
        pixel_scale_mrad = (
            self.PIXEL_SIZE_UM * 1e-3 / params.focal_length_mm * 1000
        )  # mrad/pixel

        # Timing
        utc_start = datetime.now(UTC)
        capture_duration_s = params.exposure_ms / 1000.0
        utc_stop_ts = utc_start.timestamp() + capture_duration_s
        utc_stop = datetime.fromtimestamp(utc_stop_ts, UTC)

        # Product ID: M20_MCZL_0001_0000123456_000RZL_N_01
        # MCZL = Mastcam-Z Left, MCZR = Mastcam-Z Right
        eye_code = "MCZL" if self.eye == "LEFT" else "MCZR"
        sclk_str = f"{int(sclk):010d}"
        lid = (
            f"urn:nasa:pds:mars2020_mastcamz_sci_raw:data_imagedr:"
            f"M20_{eye_code}_{sol:04d}_{sclk_str}_"
            f"{params.filter_position:03d}RZS_N_01"
        )
        file_name = f"M20_{eye_code}_{sol:04d}_{sclk_str}_{params.filter_position:03d}.IMG"

        # Generate image
        img_array = self._generate_synthetic_mars_image(params, telemetry, sol)

        metadata = PDS4Metadata(
            logical_identifier=lid,
            title=f"Mastcam-Z {self.eye} Sol {sol} {filt['name']}",
            sol=sol,
            start_date_time=utc_start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            stop_date_time=utc_stop.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            exposure_duration_ms=params.exposure_ms,
            filter_name=filt["name"],
            filter_wavelength_nm=filt["wavelength_nm"],
            focal_length_mm=params.focal_length_mm,
            camera_eye=self.eye,
            lines=img_array.shape[0],
            line_samples=img_array.shape[1],
            horizontal_fov_deg=round(fov_h, 3),
            vertical_fov_deg=round(fov_v, 3),
            pixel_scale_mrad_per_px=round(pixel_scale_mrad, 4),
            rover_latitude_deg=telemetry.latitude_deg,
            rover_longitude_deg=telemetry.longitude_deg,
            rover_altitude_m=telemetry.altitude_m,
            surface_temperature_c=telemetry.surface_temp_c,
            atm_pressure_pa=telemetry.atm_pressure_pa,
            rover_battery_pct=telemetry.battery_pct,
            rtt_seconds=telemetry.light_travel_time_s * 2,
            sclk_start=sclk,
            file_name=file_name,
        )

        return img_array, metadata

    def encode_ccsds(
        self,
        img_array: np.ndarray,
        metadata: PDS4Metadata,
        sequence_count: int,
    ) -> list[SpacecraftPacket]:
        """
        Fragment image + metadata into CCSDS space packets.
        Max payload per packet: 65528 bytes.
        """
        img_bytes = img_array.tobytes()
        meta_bytes = json.dumps(asdict(metadata)).encode("utf-8")
        payload = meta_bytes + b"\x00\xFF\x00" + img_bytes  # separator sentinel

        packets = self.encoder.fragment(
            payload=payload,
            sequence_count=sequence_count,
            secondary_header={
                "sclk": metadata.sclk_start,
                "filter": metadata.filter_wavelength_nm,
                "sol": metadata.sol,
            },
        )
        return packets


class RoverSimulator:
    """
    Top-level simulator: iterates over sols, generates image sequences,
    publishes to Kafka and stores raw PDS4 data to MinIO.
    """

    def __init__(
        self,
        kafka_bootstrap: str = "localhost:29092",
        minio_endpoint: str = "http://localhost:9000",
        minio_access: str = "minioadmin",
        minio_secret: str = "minioadmin",
        nasa_api_key: str = "DEMO_KEY",
    ):
        self.kafka_bootstrap = kafka_bootstrap
        self.minio_endpoint = minio_endpoint
        self.minio_access = minio_access
        self.minio_secret = minio_secret
        self.aws_region = os.getenv("AWS_REGION", "us-east-1")
        self.s3_bucket_raw = os.getenv("S3_BUCKET_RAW", "mastcamz-raw")
        self.s3_bucket_pds4 = os.getenv("S3_BUCKET_PDS4", "mastcamz-pds4")
        self.nasa_api_key = nasa_api_key

        self.cam_left  = MastcamZCamera("LEFT")
        self.cam_right = MastcamZCamera("RIGHT")
        self.env = MarsEnvironment()

        self._seq_counter = 0
        self._sol = int(os.getenv("SIMULATION_SOL_START", "1"))
        self._sclk_base = 700000000.0  # Approximate Perseverance SCLK at landing

        # Lazy-import heavy deps so unit tests stay fast
        self._kafka_producer = None
        self._minio_client = None
        self._init_clients()

    def _init_clients(self):
        try:
            from confluent_kafka import Producer
            self._kafka_producer = Producer({"bootstrap.servers": self.kafka_bootstrap})
        except Exception as e:
            print(f"[WARN] Kafka not available: {e}")

        try:
            from rovermars_common.storage import build_object_store_client
            # MINIO_SECURE explícito (no se infiere del esquema): en AWS el
            # endpoint es "s3.amazonaws.com" sin prefijo http(s) — ver
            # docker-compose.aws.yml / ADR-012. Construcción del cliente
            # centralizada en common/ (ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md, Fase 7).
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            self._minio_client = build_object_store_client(
                endpoint=self.minio_endpoint, access_key=self.minio_access,
                secret_key=self.minio_secret, secure=secure, region=self.aws_region,
            )
        except Exception as e:
            print(f"[WARN] MinIO not available: {e}")

    def _sclk(self) -> float:
        return self._sclk_base + self._sol * 88775.0 + random.uniform(0, 88775)

    def _publish_kafka(self, topic: str, key: str, value: dict):
        if not self._kafka_producer:
            return
        try:
            self._kafka_producer.produce(
                topic,
                key=key.encode(),
                value=json.dumps(value).encode(),
                callback=lambda err, msg: print(f"[KAFKA ERR] {err}") if err else None,
            )
            self._kafka_producer.poll(0)
        except Exception as e:
            print(f"[WARN] Kafka publish failed: {e}")

    def _store_minio(self, bucket: str, key: str, data: bytes, content_type: str):
        if not self._minio_client:
            return
        import io
        try:
            self._minio_client.put_object(
                bucket, key, io.BytesIO(data), len(data),
                content_type=content_type,
            )
        except Exception as e:
            print(f"[WARN] MinIO store failed: {e}")

    def simulate_sol_sequence(self, n_images: int = 8):
        """Simulate one sol of Mastcam-Z imaging activity."""
        telemetry = self.env.get_telemetry(self._sol)
        print(f"\n{'='*60}")
        print(f"SOL {self._sol:04d} | {telemetry}")
        print(f"{'='*60}")

        # Publish telemetry packet
        self._publish_kafka(
            "mastcamz.telemetry",
            f"sol_{self._sol:04d}",
            asdict(telemetry),
        )

        # Imaging sequence: stereo pairs at various filters
        imaging_plan = [
            (0,  26.0,  33.0, "LEFT",  "wide RGB survey"),
            (0,  26.0,  33.0, "RIGHT", "wide RGB survey"),
            (3,  110.0, 15.0, "LEFT",  "red zoom target"),
            (4,  63.0,  25.0, "LEFT",  "NIR-800 multispectral"),
            (4,  63.0,  25.0, "RIGHT", "NIR-800 multispectral"),
            (1,  48.0,  45.0, "LEFT",  "blue atmospheric"),
            (7,  110.0, 8.0,  "LEFT",  "NIR-939 mineral"),
            (7,  110.0, 8.0,  "RIGHT", "NIR-937 mineral"),
        ][:n_images]

        for filt_pos, focal, exposure, eye, desc in imaging_plan:
            cam = self.cam_left if eye == "LEFT" else self.cam_right
            params = ImageCaptureParams(
                camera_eye=eye,
                filter_position=filt_pos,
                focal_length_mm=focal,
                exposure_ms=exposure,
            )
            sclk = self._sclk()
            img_array, meta = cam.capture(params, telemetry, self._sol, sclk)
            packets = cam.encode_ccsds(img_array, meta, self._seq_counter)
            self._seq_counter = (self._seq_counter + len(packets)) % 16384

            print(f"  [{eye:5s}] Filter {filt_pos} ({cam.filters[filt_pos]['wavelength_nm']:4d}nm) "
                  f"f={focal:5.1f}mm t={exposure:5.1f}ms → "
                  f"{img_array.shape} → {len(packets)} CCSDS packets  [{desc}]")

            # Save raw IMG to MinIO
            raw_key = f"sol={self._sol:04d}/{meta.file_name}"
            self._store_minio(
                self.s3_bucket_raw,
                raw_key,
                img_array.tobytes(),
                "application/octet-stream",
            )

            # Save PDS4 XML label
            xml_label = self._generate_pds4_label(meta)
            self._store_minio(
                self.s3_bucket_pds4,
                raw_key.replace(".IMG", ".xml"),
                xml_label.encode(),
                "application/xml",
            )

            # Publish CCSDS event to Kafka
            event = {
                "sol": self._sol,
                "sclk": sclk,
                "eye": eye,
                "filter_pos": filt_pos,
                "filter_wavelength_nm": cam.filters[filt_pos]["wavelength_nm"],
                "focal_mm": focal,
                "n_packets": len(packets),
                "product_id": meta.logical_identifier,
                "file_name": meta.file_name,
                "minio_key": raw_key,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
            self._publish_kafka("mastcamz.raw.images", meta.file_name, event)

        self._sol += 1

    def _generate_pds4_label(self, meta: PDS4Metadata) -> str:
        """Generate a simplified PDS4 XML label string."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="https://pds.nasa.gov/pds4/pds/v1/PDS4_PDS_1F00.sch" ?>
<Product_Observational
  xmlns="http://pds.nasa.gov/pds4/pds/v1"
  xmlns:disp="http://pds.nasa.gov/pds4/disp/v1"
  xmlns:img="http://pds.nasa.gov/pds4/img/v1"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://pds.nasa.gov/pds4/pds/v1
    https://pds.nasa.gov/pds4/pds/v1/PDS4_PDS_1F00.xsd">
  <Identification_Area>
    <logical_identifier>{meta.logical_identifier}</logical_identifier>
    <version_id>{meta.version_id}</version_id>
    <title>{meta.title}</title>
    <information_model_version>1.15.0.0</information_model_version>
    <product_class>Product_Observational</product_class>
  </Identification_Area>
  <Observation_Area>
    <Time_Coordinates>
      <start_date_time>{meta.start_date_time}</start_date_time>
      <stop_date_time>{meta.stop_date_time}</stop_date_time>
    </Time_Coordinates>
    <Primary_Result_Summary>
      <purpose>Science</purpose>
      <processing_level>{meta.processing_level}</processing_level>
    </Primary_Result_Summary>
    <Investigation_Area>
      <name>{meta.mission_name}</name>
      <type>Mission</type>
      <Internal_Reference>
        <lid_reference>urn:nasa:pds:context:investigation:mission.mars2020</lid_reference>
        <reference_type>data_to_investigation</reference_type>
      </Internal_Reference>
    </Investigation_Area>
    <Observing_System>
      <Observing_System_Component>
        <name>{meta.spacecraft_name}</name>
        <type>Host</type>
      </Observing_System_Component>
      <Observing_System_Component>
        <name>Mastcam-Z {meta.camera_eye}</name>
        <type>Instrument</type>
        <description>Mast Camera Zoom - {meta.camera_eye} eye, filter {meta.filter_name}</description>
      </Observing_System_Component>
    </Observing_System>
    <Target_Identification>
      <name>Mars</name>
      <type>Planet</type>
    </Target_Identification>
  </Observation_Area>
  <File_Area_Observational>
    <File>
      <file_name>{meta.file_name}</file_name>
      <creation_date_time>{meta.start_date_time}</creation_date_time>
    </File>
    <Array_2D_Image>
      <local_identifier>IMAGE</local_identifier>
      <offset unit="byte">0</offset>
      <axes>2</axes>
      <axis_index_order>Last Index Fastest</axis_index_order>
      <Element_Array>
        <data_type>IEEE754MSBSingle</data_type>
        <unit>DN</unit>
      </Element_Array>
      <Axis_Array>
        <axis_name>Line</axis_name>
        <elements>{meta.lines}</elements>
        <sequence_number>1</sequence_number>
      </Axis_Array>
      <Axis_Array>
        <axis_name>Sample</axis_name>
        <elements>{meta.line_samples}</elements>
        <sequence_number>2</sequence_number>
      </Axis_Array>
    </Array_2D_Image>
  </File_Area_Observational>
  <!-- Rover position at capture time -->
  <rover_latitude_deg>{meta.rover_latitude_deg}</rover_latitude_deg>
  <rover_longitude_deg>{meta.rover_longitude_deg}</rover_longitude_deg>
  <rover_altitude_m>{meta.rover_altitude_m}</rover_altitude_m>
  <!-- Environment -->
  <surface_temperature_c>{meta.surface_temperature_c}</surface_temperature_c>
  <atm_pressure_pa>{meta.atm_pressure_pa}</atm_pressure_pa>
  <!-- Camera parameters -->
  <filter_name>{meta.filter_name}</filter_name>
  <filter_center_wavelength unit="nm">{meta.filter_wavelength_nm}</filter_center_wavelength>
  <focal_length unit="mm">{meta.focal_length_mm}</focal_length>
  <exposure_duration unit="ms">{meta.exposure_duration_ms}</exposure_duration>
  <horizontal_fov unit="deg">{meta.horizontal_fov_deg}</horizontal_fov>
  <vertical_fov unit="deg">{meta.vertical_fov_deg}</vertical_fov>
  <pixel_scale unit="mrad/pixel">{meta.pixel_scale_mrad_per_px}</pixel_scale>
  <!-- Transmission -->
  <sclk_start_count>{meta.sclk_start}</sclk_start_count>
  <light_round_trip_time unit="s">{meta.rtt_seconds}</light_round_trip_time>
</Product_Observational>
"""

    def run(self, total_sols: int = 10, interval_sec: float = 30.0):
        """Main simulation loop."""
        print(f"\n{'#'*60}")
        print("  MASTCAM-Z SIMULATOR — MARS 2020 PERSEVERANCE")
        print(f"  Jezero Crater: {JEZERO_LAT_DEG}°N {JEZERO_LON_DEG}°E")
        print(f"  Starting at Sol {self._sol}")
        print(f"{'#'*60}\n")

        for _ in range(total_sols):
            self.simulate_sol_sequence()
            if self._kafka_producer:
                self._kafka_producer.flush()
            time.sleep(interval_sec)


if __name__ == "__main__":
    sim = RoverSimulator(
        kafka_bootstrap=os.getenv("KAFKA_BOOTSTRAP", "localhost:29092"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        minio_access=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        minio_secret=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        nasa_api_key=os.getenv("NASA_API_KEY", "DEMO_KEY"),
    )
    sim.run(
        total_sols=int(os.getenv("SIMULATION_TOTAL_SOLS", "100")),
        interval_sec=float(os.getenv("SIMULATION_INTERVAL_SEC", "30")),
    )
