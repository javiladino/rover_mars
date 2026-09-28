"""
Funciones puras de calibración radiométrica y geométrica Mastcam-Z.

Se extraen del DAG (airflow/dags/mastcamz_pipeline.py) a un módulo sin
dependencias de Airflow/Kafka/MinIO para poder testearlas de forma aislada
con pytest (ver tests/test_calibration.py) y reutilizarlas también fuera
del contexto de una tarea de Airflow (notebooks, dbt macros, etc.).

Referencia: docstring original de radiometric_calibration/geometric_calibration
en el DAG — misma matemática, ahora aislada y cubierta por tests.
"""

import math

# Irradiancia solar en Marte por longitud de onda (W/m^2/nm) — valores aproximados
E_SUN_MARS_WM2NM = {
    445: 0.78, 527: 0.94, 676: 0.72, 800: 0.58,
    866: 0.52, 910: 0.49, 939: 0.47, 530: 0.95,
    630: 0.80, 908: 0.49, 937: 0.47, 1012: 0.42,
}
DEFAULT_E_SUN_WM2NM = 0.70

BIAS_DN = 2047                 # Offset CCD de 12 bits (media escala)
DARK_RATE_DN_S = 0.12          # DN/segundo a 20°C
DN_FULL_SCALE = 4096.0         # 2^12

PIXEL_SIZE_UM = 7.4            # Tamaño de píxel Mastcam-Z (µm)
STEREO_BASELINE_CM = 24.3      # Separación entre cámara izquierda y derecha


def e_sun_for_wavelength(wavelength_nm: int) -> float:
    """Irradiancia solar en Marte para una longitud de onda dada (W/m^2/nm)."""
    return E_SUN_MARS_WM2NM.get(wavelength_nm, DEFAULT_E_SUN_WM2NM)


def radiometric_factor(wavelength_nm: int) -> float:
    """Factor de conversión DN → radiancia simplificado, por filtro."""
    return round(e_sun_for_wavelength(wavelength_nm) / DN_FULL_SCALE, 8)


def bias_and_dark_correction(
    dn_raw: float,
    exposure_s: float,
    dark_rate_dn_s: float = DARK_RATE_DN_S,
    bias_dn: float = BIAS_DN,
) -> float:
    """Resta el offset de bias del CCD y la corriente de oscuridad acumulada durante la exposición."""
    return dn_raw - bias_dn - (dark_rate_dn_s * exposure_s)


def compute_iof(dn: float, wavelength_nm: int, solar_incidence_deg: float = 0.0) -> float:
    """
    Convierte un valor DN calibrado a I/F (irradiance factor), adimensional.

    I/F = (pi * L) / (E_sun * cos(theta_sun))
    con L = DN * radiometric_factor(wavelength_nm)  [W/m2/sr/nm simplificado]

    I/F ~ 0.0 (superficie absorbente) a 1.0 (reflector Lambertiano perfecto).
    """
    if not (0 <= solar_incidence_deg < 90):
        raise ValueError("solar_incidence_deg debe estar en el rango [0, 90)")

    l_radiance = dn * radiometric_factor(wavelength_nm)
    e_sun = e_sun_for_wavelength(wavelength_nm)
    cos_theta = math.cos(math.radians(solar_incidence_deg))
    return (math.pi * l_radiance) / (e_sun * cos_theta)


def ground_sample_distance_mm(range_mm: float, focal_mm: float, pixel_size_um: float = PIXEL_SIZE_UM) -> float:
    """GSD (mm/píxel) a una distancia dada, según modelo pinhole simplificado."""
    if focal_mm <= 0:
        raise ValueError("focal_mm debe ser mayor que 0")
    return round(range_mm * (pixel_size_um / 1000.0) / focal_mm, 4)


def stereo_camera_offset_m(camera_eye: str) -> float:
    """Desplazamiento en Y (metros) de cada cámara respecto al eje central del rover."""
    half_baseline_m = (STEREO_BASELINE_CM / 100.0) / 2.0
    return -half_baseline_m if camera_eye == "LEFT" else half_baseline_m
