# Contrato: esquema de salida — cobertura de imágenes por sol

**Aplica a**: la vista `science.sol_filter_coverage` (ya existente) y al job
PySpark en AWS Glue (nuevo, ver `research.md` Decisión 3). Ambos caminos
DEBEN producir exactamente este esquema, para que la comparación del
Escenario 3 (spec.md) sea una comparación de valores, no de estructura.

| Columna | Tipo | Regla |
|---|---|---|
| `sol` | integer | Clave de agrupación. No nulo. |
| `n_images` | integer | Conteo total de imágenes del sol. ≥ 0. |
| `n_left` | integer | Conteo con `camera_eye = 'LEFT'`. ≥ 0. |
| `n_right` | integer | Conteo con `camera_eye = 'RIGHT'`. ≥ 0. |
| `n_filters` | integer | Conteo distinto de `filter_wavelength_nm`. ≥ 0. |

**Invariante de aceptación** (Escenario 3, SC-004): para el mismo
subconjunto de entrada, `n_images = n_left + n_right` en ambos caminos, y
las cinco columnas coinciden fila por fila entre la vista SQL y la salida
del job de Glue.

**No forma parte de este contrato**: `filters_nm`, `first_capture`,
`last_capture` — existen en la vista SQL pero no son necesarios para la
comparación de volumen que pide el Escenario 3. El job de Glue no necesita
calcularlos.
