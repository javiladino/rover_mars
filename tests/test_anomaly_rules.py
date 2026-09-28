"""
Tests de airflow/plugins/anomaly_rules.py — reglas de negocio puras, separadas de
la tarea de Airflow que las invoca (ver Fase 7 de la guía de implementación).
"""

from anomaly_rules import classify_severity, detect_anomalies


def test_no_anomalies_when_within_thresholds():
    product = {"dust_opacity_tau": 0.8, "battery_pct": 95.0}
    assert detect_anomalies(product) == []


def test_dust_storm_detected_above_default_threshold():
    product = {"dust_opacity_tau": 2.5, "battery_pct": 95.0}
    issues = detect_anomalies(product)
    assert any("DUST_STORM_TAU" in i for i in issues)


def test_low_battery_detected_below_default_threshold():
    product = {"dust_opacity_tau": 0.5, "battery_pct": 80.0}
    issues = detect_anomalies(product)
    assert any("LOW_BATTERY" in i for i in issues)


def test_both_anomalies_can_fire_together():
    product = {"dust_opacity_tau": 3.0, "battery_pct": 70.0}
    issues = detect_anomalies(product)
    assert len(issues) == 2


def test_missing_fields_fall_back_to_safe_defaults():
    # Sin dust_opacity_tau/battery_pct en el dict, no debe explotar ni marcar anomalía.
    assert detect_anomalies({}) == []


def test_thresholds_are_parametrizable_not_hardcoded():
    product = {"dust_opacity_tau": 1.5, "battery_pct": 90.0}
    # Con los defaults (umbral 2.0) no dispara...
    assert detect_anomalies(product) == []
    # ...pero con un umbral más estricto pasado explícitamente, sí.
    issues = detect_anomalies(product, dust_storm_tau_threshold=1.0)
    assert any("DUST_STORM_TAU" in i for i in issues)


def test_classify_severity_high_when_dust_storm_present():
    assert classify_severity(["DUST_STORM_TAU=3.00", "LOW_BATTERY=80.0%"]) == "HIGH"


def test_classify_severity_medium_without_dust_storm():
    assert classify_severity(["LOW_BATTERY=80.0%"]) == "MEDIUM"


def test_detect_anomalies_is_deterministic():
    product = {"dust_opacity_tau": 2.5, "battery_pct": 80.0}
    assert detect_anomalies(product) == detect_anomalies(product)
