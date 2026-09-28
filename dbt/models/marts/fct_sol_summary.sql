-- Capa Gold declarativa: resumen por sol combinando imágenes + telemetría.
-- Complementa (no reemplaza) el JSON de Gold que build_gold_aggregates
-- sigue escribiendo en MinIO/S3 para Grafana y el dashboard estático —
-- ver ADR-001 en docs/ANALISIS_MODERN_DATA_STACK.md sobre por qué conviven
-- ambos caminos durante la migración a dbt.

with images as (
    select
        sol,
        count(*)                                    as n_images_total,
        sum(case when camera_eye = 'LEFT'  then 1 else 0 end) as n_images_left,
        sum(case when camera_eye = 'RIGHT' then 1 else 0 end) as n_images_right,
        count(distinct filter_wavelength_nm)         as n_filters_used
    from {{ ref('stg_image_products') }}
    group by sol
),

telemetry as (
    select
        sol,
        avg(surface_temp_c)        as avg_surface_temp_c,
        min(surface_temp_c)        as min_surface_temp_c,
        max(surface_temp_c)        as max_surface_temp_c,
        avg(atm_pressure_pa)       as avg_pressure_pa,
        avg(dust_opacity_tau)      as avg_dust_opacity_tau,
        max(dust_opacity_tau)      as max_dust_opacity_tau,
        min(battery_pct)           as battery_min_pct,
        max(wheel_odometry_m)      as total_drive_m
    from {{ ref('stg_telemetry_records') }}
    group by sol
)

select
    coalesce(i.sol, t.sol)                             as sol,
    coalesce(i.n_images_total, 0)                      as n_images_total,
    coalesce(i.n_images_left, 0)                       as n_images_left,
    coalesce(i.n_images_right, 0)                      as n_images_right,
    coalesce(i.n_filters_used, 0)                      as n_filters_used,
    t.avg_surface_temp_c,
    t.min_surface_temp_c,
    t.max_surface_temp_c,
    t.avg_pressure_pa,
    t.avg_dust_opacity_tau,
    t.max_dust_opacity_tau,
    (t.max_dust_opacity_tau > 2.0)                     as dust_storm_flag,
    t.battery_min_pct,
    t.total_drive_m
from images i
full outer join telemetry t on i.sol = t.sol
order by sol
