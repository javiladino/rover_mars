"""
Mars Environment & Rover Telemetry Generator

Generates physically realistic telemetry matching Perseverance measurements:
  - Surface temperature: -80 °C (night) to +20 °C (afternoon)
  - Atmospheric pressure: 600–850 Pa (seasonal variation)
  - Wind speed: 0–25 m/s
  - Battery: 90–100% (RTG-powered, Perseverance carries MMRTG)
  - Light travel time: 3–22 minutes (Earth–Mars distance varies)

References:
  - MEDA instrument (Mars Environmental Dynamics Analyzer)
  - Perseverance MMRTG: 110 W at landing, ~4.8% decay per year
  - Mars–Earth distance: 56–401 million km
"""

import math
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime

# Jezero Crater center — parametrizable por entorno (docker-compose.yml ya declara
# JEZERO_LAT/JEZERO_LON, pero antes esta constante los ignoraba por completo).
JEZERO_LAT = float(os.getenv("JEZERO_LAT", "18.4447"))
JEZERO_LON = float(os.getenv("JEZERO_LON", "77.4508"))

# Mars orbital constants
MARS_YEAR_SOLS = 668.59
MARS_SOL_SECONDS = 88775.244

# Speed of light
C_KM_S = 299792.458

# Earth–Mars min/max distance (million km)
EARTH_MARS_MIN_MKM = 56.0
EARTH_MARS_MAX_MKM = 401.0


@dataclass
class RoverTelemetry:
    sol: int
    local_mean_solar_time: float      # 0–24 h
    utc_timestamp: str

    # Position (Mars planetocentric)
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    heading_deg: float                # 0 = North, 90 = East

    # Environment (MEDA-like)
    surface_temp_c: float             # Surface temperature
    air_temp_1m_c: float              # Air temp at 1 m height
    atm_pressure_pa: float            # Atmospheric pressure (Pa)
    wind_speed_ms: float              # Wind speed m/s
    wind_direction_deg: float         # Wind direction (meteorological)
    uv_index: float                   # UV index (0–11+)
    dust_opacity_tau: float           # Atmospheric dust opacity τ

    # Power (MMRTG)
    battery_pct: float                # Battery state of charge %
    power_consumed_w: float           # Current power draw W
    mmrtg_output_w: float             # MMRTG current output W

    # Comms
    light_travel_time_s: float        # One-way light travel time
    earth_mars_dist_mkm: float        # Earth–Mars distance (Mkm)
    uhf_link_active: bool             # UHF window to MRO/MAVEN open
    data_volume_mbit_sol: float       # Downlink capacity this sol

    # Rover health
    wheel_odometry_m: float           # Total distance driven
    arm_deployed: bool
    sample_count: int                 # Cached sample tubes

    def __str__(self):
        return (
            f"Sol {self.sol:4d} | LMST {self.local_mean_solar_time:5.2f}h | "
            f"T={self.surface_temp_c:+6.1f}°C | P={self.atm_pressure_pa:5.0f}Pa | "
            f"Bat={self.battery_pct:5.1f}% | "
            f"D_Earth={self.earth_mars_dist_mkm:5.0f}Mkm | "
            f"RTT={self.light_travel_time_s*2/60:.1f}min"
        )


class MarsEnvironment:
    """
    Physically-based Martian environment model.
    Seasonal and diurnal variations calibrated against MEDA/REMS data.
    """

    def __init__(self, start_sol: int = 1, random_seed: int | None = None):
        self._rng = random.Random(random_seed)
        self._odometry = 0.0
        self._sample_count = 0

    def _seasonal_factor(self, sol: int) -> float:
        """Mars orbital position factor (0–1, peaks at perihelion ~L_s=251°)."""
        ls = (sol / MARS_YEAR_SOLS) * 360.0
        return 0.5 + 0.5 * math.cos(math.radians(ls - 251))

    def _earth_mars_distance(self, sol: int) -> float:
        """Approximate Earth–Mars distance in million km (simplified synodic cycle)."""
        synodic_period_sols = 779.9
        phase = (sol % synodic_period_sols) / synodic_period_sols
        dist = (EARTH_MARS_MIN_MKM + EARTH_MARS_MAX_MKM) / 2 + \
               (EARTH_MARS_MAX_MKM - EARTH_MARS_MIN_MKM) / 2 * math.cos(2 * math.pi * phase)
        return round(dist, 1)

    def _rover_position(self, sol: int) -> tuple[float, float, float]:
        """
        Simulate rover traverse path in Jezero Crater.
        Perseverance average speed: ~200 m/sol on good terrain.
        """
        drive_per_sol = self._rng.gauss(180, 40) if sol > 5 else 0
        drive_per_sol = max(0, drive_per_sol)
        self._odometry += drive_per_sol

        bearing_rad = math.radians(sol * 7.3 % 360)
        delta_lat = (drive_per_sol / 1000) / 111.0 * math.cos(bearing_rad)
        delta_lon = (drive_per_sol / 1000) / 111.0 * math.sin(bearing_rad)

        lat = JEZERO_LAT + delta_lat * (sol / 100)
        lon = JEZERO_LON + delta_lon * (sol / 100)
        alt = -2578.0 + self._rng.gauss(0, 3)  # Jezero floor elevation ~-2578 m MOLA

        lat = max(17.5, min(19.5, lat))
        lon = max(76.5, min(78.5, lon))
        return round(lat, 6), round(lon, 6), round(alt, 1)

    def get_telemetry(self, sol: int, lmst_hour: float | None = None) -> RoverTelemetry:
        """Generate a realistic telemetry packet for a given sol."""
        rng = self._rng

        if lmst_hour is None:
            lmst_hour = rng.uniform(8.0, 16.0)  # Daytime ops

        seasonal = self._seasonal_factor(sol)
        dist_mkm = self._earth_mars_distance(sol)
        light_time_s = (dist_mkm * 1e6) / C_KM_S

        # Temperature model: diurnal + seasonal variation
        t_mean = -60 + 25 * seasonal
        t_diurnal = 40 * math.cos(math.radians((lmst_hour - 14) * 15))
        surface_temp = t_mean + t_diurnal + rng.gauss(0, 3)
        air_temp_1m = surface_temp - 20 + rng.gauss(0, 2)

        # Pressure (Pa): seasonal CO2 cycle, 600–850 Pa
        pressure = 700 + 75 * math.sin(math.radians(sol / MARS_YEAR_SOLS * 360)) + rng.gauss(0, 10)

        # Wind (m/s)
        wind_speed = abs(rng.gauss(5, 4))
        wind_dir = rng.uniform(0, 360)

        # UV (higher at perihelion)
        uv = 3.5 * (1 + 0.5 * seasonal) + rng.gauss(0, 0.3)

        # Dust opacity (τ): 0.3 (clear) to 8.0 (global dust storm)
        # Global dust storm probability ~20% of sols around Ls 180–360
        ls = (sol / MARS_YEAR_SOLS) * 360
        storm_season = 180 < ls < 360
        if storm_season and rng.random() < 0.05:
            dust_tau = rng.uniform(2.0, 8.0)
        else:
            dust_tau = rng.uniform(0.3, 1.2)

        # MMRTG power: 110W at landing, ~4.8%/year decay
        years_elapsed = sol / 687  # ~687 sols per Earth year
        mmrtg_w = 110 * (0.952 ** years_elapsed)
        power_consumed = rng.gauss(70, 5)
        battery = min(100.0, max(85.0, 100 - (power_consumed - mmrtg_w) * 0.1 + rng.gauss(0, 0.5)))

        # UHF comms: MRO passes ~1 pass/sol, 8-min window, ~2 Mbps
        uhf_active = rng.random() < 0.85
        data_volume = rng.gauss(500, 80) if uhf_active else 0.0  # Mbit/sol

        lat, lon, alt = self._rover_position(sol)
        heading = (sol * 13.7 + rng.gauss(0, 5)) % 360

        # Random arm/sampling events
        if rng.random() < 0.15:
            self._sample_count = min(43, self._sample_count + 1)

        return RoverTelemetry(
            sol=sol,
            local_mean_solar_time=round(lmst_hour, 3),
            utc_timestamp=datetime.now(UTC).isoformat(),
            latitude_deg=lat,
            longitude_deg=lon,
            altitude_m=alt,
            heading_deg=round(heading, 1),
            surface_temp_c=round(surface_temp, 2),
            air_temp_1m_c=round(air_temp_1m, 2),
            atm_pressure_pa=round(pressure, 1),
            wind_speed_ms=round(wind_speed, 2),
            wind_direction_deg=round(wind_dir, 1),
            uv_index=round(max(0, uv), 2),
            dust_opacity_tau=round(dust_tau, 3),
            battery_pct=round(battery, 2),
            power_consumed_w=round(power_consumed, 2),
            mmrtg_output_w=round(mmrtg_w, 2),
            light_travel_time_s=round(light_time_s, 1),
            earth_mars_dist_mkm=dist_mkm,
            uhf_link_active=uhf_active,
            data_volume_mbit_sol=round(data_volume, 1),
            wheel_odometry_m=round(self._odometry, 1),
            arm_deployed=rng.random() < 0.3,
            sample_count=self._sample_count,
        )
