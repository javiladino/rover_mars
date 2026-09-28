-- Dimensión de estaciones de la Deep Space Network, enriquecida con el
-- volumen de productos recibidos por cada estación (a partir del staging).
-- Fuente de la parte estática: dbt/seeds/dsn_stations.csv (dbt seed).

with stations as (
    select * from {{ ref('dsn_stations') }}
),

received_counts as (
    select
        dsn_station,
        count(*)            as n_products_received,
        min(arrival_utc)    as first_product_arrival,
        max(arrival_utc)    as last_product_arrival
    from {{ ref('stg_image_products') }}
    where dsn_station is not null
    group by dsn_station
)

select
    s.dsn_station,
    s.antenna_id,
    s.location_country,
    s.antenna_diameter_m,
    s.longitude_deg,
    s.latitude_deg,
    coalesce(r.n_products_received, 0) as n_products_received,
    r.first_product_arrival,
    r.last_product_arrival
from stations s
left join received_counts r on r.dsn_station = s.dsn_station
