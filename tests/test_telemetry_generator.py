"""
Tests del generador de telemetría ambiental (simulator/telemetry_generator.py).

No se testea el valor exacto de cada muestra (es un modelo con ruido gaussiano),
sino que los rangos físicos documentados en el README se respeten de forma
consistente a lo largo de muchos soles — el tipo de test que detecta una
fórmula rota (p. ej. una unidad mal convertida) sin ser frágil ante el ruido.
"""

import pytest
from telemetry_generator import MarsEnvironment, RoverTelemetry

N_SOLS_SAMPLE = 300


@pytest.fixture
def env():
    return MarsEnvironment(start_sol=1, random_seed=42)


def test_get_telemetry_returns_rover_telemetry_instance(env):
    sample = env.get_telemetry(sol=10)
    assert isinstance(sample, RoverTelemetry)
    assert sample.sol == 10


@pytest.mark.parametrize("sol", [1, 50, 200, 668, 1500])
def test_surface_temperature_within_documented_range(env, sol):
    sample = env.get_telemetry(sol=sol)
    # README: superficie -120 a +50 °C — se deja margen para el ruido gaussiano
    assert -140.0 <= sample.surface_temp_c <= 70.0


def test_pressure_stays_within_seasonal_co2_cycle_range():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    pressures = [env_local.get_telemetry(sol=s).atm_pressure_pa for s in range(1, N_SOLS_SAMPLE)]
    # README: 600–850 Pa; el modelo real puede rozar el límite por ruido, no cruzarlo groseramente
    assert min(pressures) > 500.0
    assert max(pressures) < 950.0


def test_wind_speed_is_never_negative():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    speeds = [env_local.get_telemetry(sol=s).wind_speed_ms for s in range(1, N_SOLS_SAMPLE)]
    assert min(speeds) >= 0.0


def test_dust_opacity_within_documented_range():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    taus = [env_local.get_telemetry(sol=s).dust_opacity_tau for s in range(1, N_SOLS_SAMPLE)]
    # README: tau = 0.3–8.0
    assert min(taus) >= 0.3
    assert max(taus) <= 8.0


def test_battery_percentage_stays_within_operational_bounds():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    batteries = [env_local.get_telemetry(sol=s).battery_pct for s in range(1, N_SOLS_SAMPLE)]
    assert min(batteries) >= 85.0
    assert max(batteries) <= 100.0


def test_mmrtg_output_decays_over_mission_lifetime(env):
    early = env.get_telemetry(sol=1).mmrtg_output_w
    late = env.get_telemetry(sol=2000).mmrtg_output_w
    # ~4.8%/año de decaimiento -> a mayor sol, menor potencia MMRTG
    assert late < early


def test_rover_position_stays_within_jezero_crater_clamp():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    for s in range(1, N_SOLS_SAMPLE, 10):
        sample = env_local.get_telemetry(sol=s)
        assert 17.5 <= sample.latitude_deg <= 19.5
        assert 76.5 <= sample.longitude_deg <= 78.5


def test_wheel_odometry_is_monotonically_non_decreasing():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    previous = 0.0
    for s in range(1, 50):
        sample = env_local.get_telemetry(sol=s)
        assert sample.wheel_odometry_m >= previous
        previous = sample.wheel_odometry_m


def test_light_travel_time_within_earth_mars_distance_bounds():
    env_local = MarsEnvironment(start_sol=1, random_seed=7)
    for s in range(1, N_SOLS_SAMPLE, 15):
        sample = env_local.get_telemetry(sol=s)
        # README: 3–22 minutos de tiempo de viaje de la luz (one-way)
        minutes = sample.light_travel_time_s / 60.0
        assert 3.0 <= minutes <= 23.0
