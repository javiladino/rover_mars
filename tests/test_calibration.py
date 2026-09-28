"""
Tests de la matemática de calibración radiométrica/geométrica (airflow/plugins/calibration.py).

Cubre exactamente la fórmula documentada en el DAG (mastcamz_pipeline.py):
  I/F = (pi * L) / (E_sun * cos(theta_sun))
y el modelo de Ground Sample Distance usado por geometric_calibration.
"""

import math

import pytest
from calibration import (
    BIAS_DN,
    DARK_RATE_DN_S,
    STEREO_BASELINE_CM,
    bias_and_dark_correction,
    compute_iof,
    e_sun_for_wavelength,
    ground_sample_distance_mm,
    radiometric_factor,
    stereo_camera_offset_m,
)


def test_e_sun_known_wavelength_returns_table_value():
    assert e_sun_for_wavelength(530) == 0.95


def test_e_sun_unknown_wavelength_falls_back_to_default():
    assert e_sun_for_wavelength(999) == 0.70


def test_radiometric_factor_matches_manual_calculation():
    # e_sun(530) / 4096 redondeado a 8 decimales
    assert radiometric_factor(530) == round(0.95 / 4096.0, 8)


def test_bias_and_dark_correction_removes_offset_and_dark_current():
    dn_raw = 2500.0
    exposure_s = 10.0
    corrected = bias_and_dark_correction(dn_raw, exposure_s)
    expected = dn_raw - BIAS_DN - (DARK_RATE_DN_S * exposure_s)
    assert corrected == pytest.approx(expected)


def test_compute_iof_at_zero_incidence_is_positive_and_finite():
    iof = compute_iof(dn=1000, wavelength_nm=530, solar_incidence_deg=0.0)
    assert iof > 0
    assert math.isfinite(iof)


def test_compute_iof_increases_with_solar_incidence_angle():
    # A mayor ángulo de incidencia (más oblicuo), cos(theta) baja -> I/F sube
    iof_low_angle  = compute_iof(dn=1000, wavelength_nm=530, solar_incidence_deg=10.0)
    iof_high_angle = compute_iof(dn=1000, wavelength_nm=530, solar_incidence_deg=60.0)
    assert iof_high_angle > iof_low_angle


def test_compute_iof_rejects_incidence_angle_out_of_range():
    with pytest.raises(ValueError):
        compute_iof(dn=1000, wavelength_nm=530, solar_incidence_deg=90.0)
    with pytest.raises(ValueError):
        compute_iof(dn=1000, wavelength_nm=530, solar_incidence_deg=-1.0)


def test_ground_sample_distance_matches_original_dag_formula():
    # Fórmula original en el DAG: gsd_mm_10m = 10000 * 0.0074 / focal
    focal_mm = 26.0
    expected = round(10000 * 0.0074 / focal_mm, 2)
    actual = ground_sample_distance_mm(range_mm=10000, focal_mm=focal_mm)
    assert actual == pytest.approx(expected, abs=0.01)


def test_ground_sample_distance_rejects_invalid_focal():
    with pytest.raises(ValueError):
        ground_sample_distance_mm(range_mm=10000, focal_mm=0)


def test_stereo_camera_offset_left_and_right_are_symmetric_and_match_baseline():
    left = stereo_camera_offset_m("LEFT")
    right = stereo_camera_offset_m("RIGHT")
    assert left == -right
    assert abs(left - right) == pytest.approx(STEREO_BASELINE_CM / 100.0)
