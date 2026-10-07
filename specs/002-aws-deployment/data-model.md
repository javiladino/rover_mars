# Fase 1 — Modelo de Datos: Despliegue Híbrido en AWS con Datos Reales

**Feature**: 002-aws-deployment · **Fecha**: 2026-10-07

## Cambio de esquema: marca de origen en `image_products`

La spec (FR-005) exige que todo registro quede marcado como `real` o
`simulado`. Hoy `image_products` (`database/schema.sql`) no distingue
origen — todo lo que existe fue generado por el simulador. Se agrega una
columna, no una tabla nueva, para no duplicar el modelo existente:

```sql
ALTER TABLE image_products
  ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'simulado'
    CHECK (origen IN ('real', 'simulado'));
```

- **Compatible hacia atrás**: el `DEFAULT 'simulado'` hace que las 100+
  filas ya generadas por el simulador queden correctamente marcadas sin
  tocarlas una por una.
- **Idempotente**: `ADD COLUMN IF NOT EXISTS` no falla si ya se aplicó.
- Las vistas que consumen `image_products` (`science.sol_filter_coverage`,
  `science.rover_traverse`) no necesitan cambios — `SELECT *`/columnas
  explícitas ya existentes siguen funcionando; se agrega `origen` donde se
  quiera mostrar la distinción (p. ej. el dashboard).

## Entidades

### ProductoPDS4Real

Representa un producto real descargado del bundle `mastcamz_ops_raw` (ver
`research.md`, Decisión 2). No es una tabla nueva — es el conjunto de
campos que la ingesta real escribe en `image_products` además de los que ya
existen.

| Campo | Origen | Notas |
|---|---|---|
| `product_id` | Nombre real del archivo, sin extensión (ej. `ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03`) | Reemplaza el `product_id` sintético que genera el simulador para este registro |
| `sol` | Segundo campo del nombre de archivo | Ya existe en `image_products.sol` |
| `sclk` | Tercer campo del nombre de archivo | Ya existe en `image_products` |
| `camera_eye` | `ZL6` → `LEFT`, `ZR2` → `RIGHT` | Mapeo explícito, ya existe la columna |
| `checksum_fuente` | De la etiqueta PDS4 (`.xml`) del producto, no del manifiesto — ver research.md Decisión 2 (revisada) | Se valida contra el archivo descargado antes de aceptar el producto (FR-003/FR-004) |
| `origen` | Constante `'real'` para estos registros | Columna nueva (ver arriba) |
| `raw_s3_key` | Ruta del objeto en el bucket `raw` | Ya existe el patrón de key en el código del simulador; se reutiliza |

### ResultadoComparacionCobertura

No persiste en base — es la salida en memoria del job de Glue y de la
consulta SQL, comparadas fila por fila en el mismo esquema de columnas que
`science.sol_filter_coverage` ya expone (ver `contracts/`):

| Campo | Tipo |
|---|---|
| `sol` | integer |
| `n_images` | integer |
| `n_left` | integer |
| `n_right` | integer |
| `n_filters` | integer |

## Relaciones

```
image_products (existente, + columna origen)
  └── consumida por → science.sol_filter_coverage (vista SQL, sin cambios)
  └── consumida por → job PySpark en Glue, vía JDBC (nuevo)
                          └── su salida se compara contra la vista SQL
                              usando el contrato de columnas de arriba
```

No se introduce ninguna tabla nueva. El cambio de esquema es mínimo a
propósito: la spec pide demostrar que el origen real conviven con el
simulado en el mismo modelo, no construir un modelo paralelo.
