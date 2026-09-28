-- Equivalente declarativo (dbt) de la vista science.sol_filter_coverage
-- definida en database/schema.sql — misma métrica de negocio, ahora
-- versionada y testeada como parte del proyecto dbt (ADR-001).

select
    sol,
    count(distinct filter_wavelength_nm)                                as n_filters,
    count(*)                                                             as n_images,
    sum(case when camera_eye = 'LEFT'  then 1 else 0 end)                as n_left,
    sum(case when camera_eye = 'RIGHT' then 1 else 0 end)                as n_right,
    min(capture_utc)                                                     as first_capture,
    max(capture_utc)                                                     as last_capture
from {{ ref('stg_image_products') }}
group by sol
order by sol
