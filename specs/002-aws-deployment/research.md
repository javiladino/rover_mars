# Fase 0 — Investigación: Despliegue Híbrido en AWS con Datos Reales

**Feature**: 002-aws-deployment · **Fecha**: 2026-10-07

Este documento resuelve las decisiones técnicas que la spec (`spec.md`) deja
abiertas, antes de pasar a diseño (Fase 1). Cada decisión está verificada
contra el código real del repositorio o contra una fuente externa consultada
en esta sesión — ninguna es una suposición.

---

## Decisión 1 — Credenciales S3 en AWS: `IamAwsProvider`, no `boto3`

**Decisión**: Modificar `common/rovermars_common/storage.py` para que, cuando
el destino sea S3 real (`secure=True`) y no se reciban `access_key`/`secret_key`
explícitas, el cliente MinIO use el proveedor de credenciales
`minio.credentials.IamAwsProvider` en lugar de claves estáticas. El cliente
local (MinIO, `secure=False`) no cambia.

**Razón**: El error real observado en el despliegue
(`minio.error.S3Error: AccessDenied`) ocurre porque `MINIO_ACCESS_KEY`/
`MINIO_SECRET_KEY` se mapean a `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`,
dejadas vacías a propósito para usar el rol IAM del EC2 — pero el SDK de
MinIO, con claves vacías, firma como anónimo.

`minio-py` (pin actual: `minio>=7.2.7` en `simulator/`, `ingestion/` y
`airflow/requirements.txt`) incluye `IamAwsProvider`, que lee credenciales
temporales del Instance Metadata Service del EC2 — el mismo mecanismo que
usa `boto3` internamente — sin agregar una dependencia nueva ni tocar un
solo call-site de `.put_object`/`.fput_object`/`.get_object` en
`mastcamz_pipeline.py`, `meda_pipeline.py`, `mastcamz_simulator.py` ni
`dsn_receiver.py`. El cliente que ya construye `build_object_store_client`
sigue siendo un objeto `Minio` idéntico en toda la base de código.

**Alternativas consideradas**:
- **Reescribir todo a `boto3`**: descartado. Significa tocar cada
  `put_object`/`get_object` en al menos 4 módulos, para lograr exactamente
  lo mismo que ya resuelve `IamAwsProvider` sin ese costo.
- **Guardar claves de acceso estáticas en SSM**: descartado. Contradice la
  intención ya tomada (Principio VI/V) de usar credenciales de rol de corta
  vida en vez de claves de larga vida que hay que rotar a mano.

---

## Decisión 2 — Fuente de datos reales: bundle `mastcamz_ops_raw`, no `sci_calibrated`

**Decisión**: La ingesta de productos reales de Mastcam-Z usa el bundle
público del archivo PDS de JPL:
`https://planetarydata.jpl.nasa.gov/img/data/mars2020/mars2020_mastcamz_ops_raw/`
(EDR, sin calibrar) — no `mars2020_mastcamz_sci_calibrated/`.

**Razón**: Se verificó por acceso directo (vía fetch, 2026-10-07) que
`sci_calibrated/data/<sol>/` separa los productos en subcarpetas `iof/` y
`rad/` — es decir, ya vienen con la calibración radiométrica aplicada
(conversión a I/F o radiancia). Nuestra capa Silver existente
(`airflow/plugins/calibration.py`) hace exactamente ese paso
(bias/dark/flat-field/DN→I/F) sobre lo que llega a Bronze. Si el origen real
ya viniera calibrado, Silver dejaría de tener sentido o quedaría
duplicando/contradiciendo un cálculo ya hecho — rompe el contrato Medallion
(Principio II: "Silver es donde ocurre toda calibración/enriquecimiento").
El bundle `ops_raw` es el correspondiente real a una capa Raw inmutable y
sin calibrar.

**Mecanismo de descubrimiento (REVISADO 2026-10-07, tras una corrida real
fallida — ver tarea T021 de tasks.md)**: la versión original de esta
decisión asumía que `collection_data_inventory.csv` (~44 MB, expuesto en
`mars2020_mastcamz_ops_raw/data/`) era un manifiesto con columnas de ruta y
checksum por producto. **Eso era incorrecto** — se descubrió recién al
correr el script contra la red real, no al inspeccionar el archivo antes de
escribir código. El CSV es un inventario PDS4 estándar de **solo 2 columnas
sin encabezado**: estado de miembro + LIDVID en minúscula (ej.
`P,urn:nasa:pds:mars2020_mastcamz_ops_raw:data:zl0_0001_0667035647_...::3.0`).
No tiene ruta de archivo ni checksum utilizables para descargar, y el LIDVID
no alcanza para reconstruir el nombre real del archivo porque PDS4
normaliza los identificadores a minúscula, perdiendo la mayúscula/minúscula
real de los campos del nombre.

El mecanismo real, verificado navegando el archivo público directamente, es
más profundo de lo asumido:

```
mars2020_mastcamz_ops_raw/data/sol/{sol:05d}/ids/edr/zcam/
```

(nótese: la carpeta de sol usa **5 dígitos**, no 4 como en `sci_calibrated`).
Esa carpeta expone un listado HTTP estándar con los `.IMG`/`.xml`/`.JPG` del
sol. Sigue siendo acotado en el sentido que importa para la spec (un `GET`
por sol pedido, no un recorrido del árbol completo de 658 sols) — el límite
pasó de "un manifiesto único" a "una carpeta por sol", pero el principio
(no recorrer todo el archivo) se mantiene.

**Checksum**: al no venir en el manifiesto, se lee de la propia etiqueta
PDS4 (`.xml`) de cada producto, que trae su `<md5_checksum>` oficial — más
fiel al dominio real que inventar una columna que no existe.

**Formato real de producto** (confirmado navegando `ops_raw` directamente,
no solo `sci_calibrated`):

```
ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.IMG
ZL6_0100_0675828555_098ECM_N0040218ZCAM01000_026080J03.xml
```

Prefijo de cámara (`ZL`=izquierda, `ZR`=derecha), sol (4 dígitos dentro del
nombre, aunque la carpeta use 5), SCLK, resto de campos de la misión real —
**distinto** del formato `M20_MCZL_0001_0000700032_000RZL_N_01` documentado
hoy en el README del simulador, que es una convención simplificada e
inventada. El código de producto (`098ECM` acá vs. `098IOF` en
`sci_calibrated`) varía según el nivel de procesamiento — ECM es
demosaicado sin calibrar, coherente con que este es el bundle Raw.

**Hallazgo derivado (fuera de alcance de esta feature, se deja registrado)**:
el Principio I exige marcar como "simplificación deliberada" cualquier
formato inventado, y hoy el formato del simulador no lo está. No se corrige
en esta spec — es trabajo del simulador, no del despliegue AWS — pero
queda anotado para una spec futura.

**Alternativas consideradas**:
- **API `api.nasa.gov` (Mars Rover Photos)**: descartada. No ofrece
  productos Mastcam-Z de Perseverance con la granularidad PDS4 (etiqueta +
  checksum) que exige FR-003 de la spec.
- **Recorrer el árbol completo del archivo público**: descartado por
  innecesario y menos respetuoso del servicio — el CSV manifiesto ya resuelve
  la selección acotada en una sola descarga.

---

## Decisión 3 — PySpark en AWS Glue, leyendo por JDBC contra RDS

**Decisión**: El job de Glue (PySpark) se conecta a la misma base
`rover_mars` en RDS vía una conexión JDBC de Glue (`aws_glue_connection`), lee
la tabla `image_products` — la misma que ya consulta
`science.sol_filter_coverage` — y calcula la cobertura por sol en Spark para
compararla fila por fila contra la vista SQL existente.

**Razón**: El objetivo de este escenario (spec, Escenario 3) es evaluar si
Spark se justifica frente a SQL para este volumen, con una comparación
directa. Leer la misma tabla por dos caminos distintos (SQL vs PySpark) es
la comparación más honesta: ambos calculan sobre la misma fuente, así que
cualquier diferencia de resultado es un bug, no un artefacto de datos
distintos. Inventar una forma paralela de "Bronze/Silver en S3" solo para
este job agregaría una superficie de datos que el resto del proyecto no usa
y que nadie mantendría después.

**Qué falta en Terraform**: `infra/aws/glue_athena.tf` ya provisiona el
Glue Catalog y un crawler (sobre Gold en S3, no sobre RDS). Para este job
hace falta agregar: `aws_glue_connection` (tipo JDBC, apuntando a
`aws_db_instance.rover_mars`), una regla de ingreso en
`aws_security_group.rds` que acepte conexiones desde el security group que
Glue usa para la conexión, y el recurso `aws_glue_job` en sí con su script.

**Alternativas consideradas**:
- **EMR Serverless**: descartado — más caro y más complejo de operar que un
  Glue Job para este volumen de datos de demo (Principio VI).
- **Spark standalone en el propio EC2**: descartado — el EC2 ya está
  limitado en memoria (ver incidente de esta sesión: `t3.small` con swap en
  uso), y correr Spark ahí no es lo que un reclutador entiende por "stack
  con Spark gestionado".
- **Leer Bronze/Silver desde S3 en un formato nuevo**: descartado, por las
  razones de la sección "Razón" arriba.
