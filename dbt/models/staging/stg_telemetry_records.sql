-- Staging: telemetría ambiental normalizada.

with source as (
    select * from {{ source('rover_mars_raw', 'telemetry_records') }}
)

select
    id                      as telemetry_pk,
    sol,
    utc_timestamp,
    latitude_deg,
    longitude_deg,
    surface_temp_c,
    air_temp_1m_c,
    atm_pressure_pa,
    wind_speed_ms,
    uv_index,
    dust_opacity_tau,
    battery_pct,
    mmrtg_output_w,
    earth_mars_dist_mkm,
    light_travel_time_s,
    wheel_odometry_m
from source
