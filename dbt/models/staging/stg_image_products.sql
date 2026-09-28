-- Staging: normaliza tipos y nombres de columnas de image_products.
-- Materializado como view: es barato de mantener y no duplica los datos
-- que ya viven en public.image_products.

with source as (
    select * from {{ source('rover_mars_raw', 'image_products') }}
)

select
    id                      as image_product_pk,
    product_id,
    file_name,
    sol,
    sclk,
    camera_eye,
    filter_wavelength_nm,
    focal_mm,
    dsn_station,
    light_delay_s,
    capture_utc,
    arrival_utc,
    product_type,
    processing_stage,
    quality_flag,
    radiometric_factor,
    dust_opacity_tau,
    minio_silver_key,
    minio_gold_key,
    rover_location
from source
