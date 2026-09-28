"""
Reglas de detección de anomalías — separadas de la tarea de Airflow que las invoca.

Antes, esta lógica vivía inline dentro de la tarea `anomaly_detection` del DAG, con
los umbrales hardcodeados (τ > 2.0, batería < 87.0) y un comentario reconociendo que
"en producción estos umbrales vendrían de la calibración del instrumento MEDA". Este
módulo resuelve las dos cosas: separa la regla de negocio (pura, sin I/O) de la
orquestación (Kafka/Postgres/XCom), y hace los umbrales parametrizables por entorno
en vez de estar fijos en el código.

Determinismo: dado el mismo `product` y los mismos umbrales, siempre devuelve el
mismo resultado — no hay estado ni I/O. Ver tests/test_anomaly_rules.py.
"""

import os

DEFAULT_DUST_STORM_TAU_THRESHOLD = float(os.getenv("DUST_STORM_TAU_THRESHOLD", "2.0"))
DEFAULT_LOW_BATTERY_PCT_THRESHOLD = float(os.getenv("LOW_BATTERY_PCT_THRESHOLD", "87.0"))


def detect_anomalies(
    product: dict,
    dust_storm_tau_threshold: float = DEFAULT_DUST_STORM_TAU_THRESHOLD,
    low_battery_pct_threshold: float = DEFAULT_LOW_BATTERY_PCT_THRESHOLD,
) -> list[str]:
    """Devuelve la lista de códigos de anomalía detectados en un producto (vacía si no hay ninguna)."""
    issues = []

    tau = product.get("dust_opacity_tau", 0.5)
    if tau > dust_storm_tau_threshold:
        issues.append(f"DUST_STORM_TAU={tau:.2f}")

    battery = product.get("battery_pct", 100.0)
    if battery < low_battery_pct_threshold:
        issues.append(f"LOW_BATTERY={battery:.1f}%")

    return issues


def classify_severity(issues: list[str]) -> str:
    """HIGH si hay una tormenta de polvo entre las anomalías, MEDIUM en cualquier otro caso con anomalías."""
    return "HIGH" if any("DUST_STORM" in i for i in issues) else "MEDIUM"
