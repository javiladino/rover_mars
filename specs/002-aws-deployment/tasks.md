# Tasks: Despliegue Híbrido en AWS con Datos Reales de Mastcam-Z

**Input**: Documentos de diseño en `/specs/002-aws-deployment/`
**Prerequisitos**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md — todos ya existentes.

**Organización**: por escenario de usuario (spec.md), en el mismo orden de prioridad (P1, P1, P2, P3). Varias tareas de Fase 1 ya se ejecutaron en el despliegue real de esta sesión y quedan marcadas como completas, con la fecha, para que este archivo refleje el estado real y no un plan ficticio.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: se puede hacer en paralelo (archivos distintos, sin dependencias entre sí)
- **[Story]**: a qué escenario de spec.md pertenece (US1=Escenario 1, US2=Escenario 2, US3=Escenario 3, US4=Escenario 4)
- Fase de Setup y Fase Fundacional no llevan etiqueta de historia (son compartidas)

---

## Fase 1: Setup — ya ejecutado en el despliegue real (2026-10-06/07)

**Propósito**: registro de lo que ya corrió contra AWS real en esta sesión, antes de este tasks.md. No requiere acción nueva.

- [x] T001 Aplicar `aws_budgets_budget.monthly` antes de cualquier otro recurso de pago — `infra/aws/budgets.tf` (FR-001, hecho 2026-10-06)
- [x] T002 Revisar `terraform plan` completo antes de cada `apply` en `infra/aws/` — práctica seguida en todo el despliegue (FR-002)
- [x] T003 [P] Restringir SSH, Airflow (8080) y Kafka UI (8085) a la IP del operador en `infra/aws/ec2.tf`, y cerrar 8080 por completo a favor de túnel SSH (hecho 2026-10-06/07)
- [x] T004 Aplicar `database/init.sql`, `database/schema.sql` y `database/meda_schema.sql` contra RDS vía `psql` desde el EC2 — nunca se habían corrido contra la base real (hecho 2026-10-06)
- [x] T005 Corregir permisos de `dbt/` en el EC2 con `chmod -R o+rwX dbt/` — mismo fix que el runbook on-prem (hecho 2026-10-06)

**Checkpoint**: infraestructura base desplegada, Airflow accesible, `dbt build` en verde contra RDS. EC2 y RDS están `stopped` (no terminados) al momento de escribir este archivo.

---

## Fase 2: Fundacional (bloqueante para US1-cierre y US2)

**Propósito**: sin esto, `build_gold_aggregates` sigue fallando con `AccessDenied` y la ingesta real (US2) no puede escribir a S3.

**⚠️ CRÍTICO**: ningún trabajo de US2 puede completarse sin T006-T009. No requiere EC2/RDS encendidos — es desarrollo y test local.

- [x] T006 [P] Modificar `build_object_store_client` en `common/rovermars_common/storage.py`: cuando `secure=True` y no se reciban `access_key`/`secret_key`, usar `minio.credentials.IamAwsProvider` en vez de credenciales estáticas (research.md, Decisión 1) — hecho 2026-10-07
- [x] T007 [P] Agregar en `tests/test_storage.py` un test que mockee `minio.credentials.IamAwsProvider` y verifique que se usa cuando `secure=True` sin claves, sin red real (Principio IV) — hecho 2026-10-07, con `unittest.mock` (no se agregó `pytest-mock`, no estaba en `requirements-dev.txt`)
- [x] T008 Correr `ruff check common/ tests/test_storage.py` — debe pasar sin hallazgos (depende de T006, T007) — **`All checks passed!`**, corrido contra Python 3.11.10 real (venv `/tmp/rovermars_test_venv`)
- [x] T009 Correr `pytest tests/test_storage.py -v` — debe pasar en verde (depende de T006, T007) — **8 passed**; además la suite completa (`pytest tests/`) da **98 passed**, sin regresiones en los demás módulos
- [x] T010 [P] Agregar columna de origen en `database/schema.sql`: columna en el `CREATE TABLE image_products` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS origen ...` idempotente después, para cubrir la tabla que ya existe en RDS (data-model.md) — hecho 2026-10-07; **falta aplicarlo contra RDS real** (eso es parte de T011/T021, con el servidor encendido)

**Checkpoint**: cliente de almacenamiento listo para AWS real, verificado con `pytest`/`ruff` reales (Principio IV). US2 y el cierre de US1 pueden empezar.

---

## Fase 3: Escenario 1 — Despliegue acotado en AWS, cierre (Prioridad: P1)

**Meta**: dejar evidencia de que el despliegue corre de punta a punta y se destruye sin dejar gasto residual (spec.md, Escenario 1).

**Prueba independiente**: `mastcamz_full_pipeline`/`meda_full_pipeline` corren sin `AccessDenied`; la facturación del periodo queda exportada; tras `terraform destroy` no quedan recursos de pago.

**⚠️ Estas tareas se ejecutan al final, no ahora** — dependen de que T006-T009 estén validadas contra AWS real (no solo en local) y de que US2/US3 ya hayan corrido al menos una vez, para que la "corrida completa" tenga datos reales que mostrar.

- [x] T011 [US1] Con EC2 y RDS encendidos, disparar `mastcamz_full_pipeline` y `meda_full_pipeline` completos y confirmar en los logs que `build_gold_aggregates` ya no falla con `AccessDenied` (depende de T006-T009, T021, T029) — hecho 2026-10-07, con un hallazgo real antes de lograrlo: la primera corrida manual **sí volvió a fallar con `AccessDenied`** — no porque el fix estuviera mal, sino porque la imagen Docker de `airflow_scheduler`/`airflow_webserver` nunca se había reconstruido tras el cambio en `common/rovermars_common/storage.py` (confirmado comparando el archivo dentro del contenedor vs. el del host: el contenedor no tenía `IamAwsProvider`). Se reconstruyó con `docker compose build airflow_scheduler airflow_webserver airflow_init` y se relanzó — la siguiente corrida (`scheduled__2026-10-07T19:30:00+00:00`) de `mastcamz_full_pipeline` terminó **completa en `success`**, con `build_gold_aggregates: success` confirmado explícitamente contra S3 real (sin `AccessDenied`). `meda_full_pipeline` no pudo completarse en esta ventana: su primera tarea (`poll_meda_queue`) falla con `TopicNotFoundError: telemetry.meda.raw not found` porque `rover_simulator`/`dsn_receiver` llevan horas `Exited (137)` (OOM del `t3.small`, memoria libre cayó a 210 MiB) y nunca crearon ese tópico — **hallazgo real pero fuera de alcance de esta feature** (no relacionado con `AccessDenied`/`IamAwsProvider`; el `build_gold_aggregates` de MEDA usa el mismo helper `_get_minio()` ya confirmado arreglado, solo que no se pudo ejecutar porque la tarea previa nunca llegó a correr). Se decidió no arriesgar otro OOM reiniciando el simulador con memoria tan ajustada — la evidencia de `mastcamz_full_pipeline` ya prueba el fix contra AWS real de punta a punta
- [x] T012 [US1] Exportar la facturación del periodo desde Cost Explorer como evidencia del despliegue (FR-009) — hecho 2026-10-07, guardado en `specs/002-aws-deployment/evidence/costo_despliegue.md`: `ActualSpend: $0.00` de `$40.00` en `rovermars-monthly-budget` (AWS Budgets) y desglose por servicio de Cost Explorer, con nota honesta sobre la demora de ~24h de Cost Explorer en reflejar el uso de hoy (el costo real del job de Glue, medido directo vía `aws glue get-job-run`, está en T031)
- [x] T013 [US1] Ejecutar `terraform destroy`, y verificar con `aws ec2 describe-instances` / `aws rds describe-db-instances` que no quedan recursos de pago activos (FR-010, SC-006) — hecho 2026-10-07: `terraform destroy` eliminó 55 de 57 recursos (EC2, RDS, Glue, IAM, CloudFront, SNS, SSM, VPC Endpoint, security groups); los 2 recursos restantes son `aws_s3_bucket.data_lake["raw"]` y `["gold"]`, que fallaron a propósito con `BucketNotEmpty` (no tienen `force_destroy` — ver nota en research.md/tasks.md: conservan los 76 productos PDS4 reales y el agregado Gold como evidencia, S3 sin cómputo no genera costo por hora). Verificado con `aws ec2 describe-instances` y `aws rds describe-db-instances`: ambos vacíos, ningún recurso de pago activo. `terraform state list` confirma solo los 2 buckets restantes. **Actualización 2026-10-08**: por pedido explícito del usuario (no quería dejar nada corriendo en la cuenta, ni siquiera storage barato), se vaciaron (purgando todas las versiones, el bucket tenía versionado activado) y borraron también los 2 buckets restantes, y se sacaron del estado de Terraform (`terraform state rm`) — el estado quedó en 0 recursos. Barrida adicional de verificación (IPs elásticas, volúmenes/snapshots EBS huérfanos, snapshots RDS, NAT Gateways, load balancers, log groups de CloudWatch, y Glue/Athena/CloudFront/SNS/Lambda/SSM por nombre `rovermars`): **todo vacío**, sin ningún rastro de la feature en la cuenta
- [x] T014 [US1] Documentar en un anexo de `quickstart.md` el tiempo real entre `apply` y `destroy`, y el costo total observado en Cost Explorer — hecho 2026-10-07, anexo agregado al final de `quickstart.md` con el costo real ($0.00 Budgets + $0.025/corrida de Glue medido aparte), el detalle de que EC2/RDS estuvieron `stopped` entre sesiones (no facturando) y el resultado exacto del `destroy` (55/57, los 2 buckets con datos reales preservados a propósito)

**Checkpoint**: Escenario 1 completo — evidencia de costo y de funcionamiento capturada, infraestructura destruida.

---

## Fase 4: Escenario 2 — Ingesta de productos reales PDS4 (Prioridad: P1)

**Meta**: productos reales de Mastcam-Z en Raw, marcados como tales, sin duplicarse en re-ejecuciones (spec.md, Escenario 2).

**Prueba independiente**: descargar un subconjunto acotado, verificar checksum, repetir la ingesta y confirmar 0 duplicados.

**Requiere EC2+RDS encendidos solo en T021/T022** — el desarrollo y los tests (T015-T020) son locales.

- [x] T015 [P] [US2] Crear `ingestion/pds4_real_ingest.py`: descargar `collection_data_inventory.csv` del bundle `mastcamz_ops_raw` y filtrar un subconjunto acotado de 1-2 sols (research.md, Decisión 2) — hecho 2026-10-07
- [x] T016 [US2] En `ingestion/pds4_real_ingest.py`, descargar `.IMG` + `.xml` por producto del subconjunto y validar su checksum contra la etiqueta PDS4 antes de aceptarlo; si no coincide, poner en cuarentena con motivo explícito (FR-003, FR-004) — hecho. **Rediseñado tras una corrida real fallida** (T021): el manifiesto `collection_data_inventory.csv` resultó ser un inventario PDS4 sin encabezado ni columnas de ruta/checksum (solo LIDVIDs en minúscula) — no servía para descargar. Se reemplazó por listado de directorio por sol (`data/sol/{sol:05d}/ids/edr/zcam/`, carpeta de 5 dígitos, verificada navegando el archivo real) y por leer el checksum de la etiqueta `.xml` de cada producto en vez del manifiesto. Ver research.md, Decisión 2 (revisada)
- [x] T017 [US2] En `ingestion/pds4_real_ingest.py`, subir cada producto validado al bucket `raw` usando `build_object_store_client` (ya corregido en T006), preservando el `product_id` real (ej. `ZL6_0100_0675828555_098IOF_N0040218ZCAM01000_026080A03`) — FR-003 — hecho
- [x] T018 [US2] En `ingestion/pds4_real_ingest.py`, insertar cada producto en `image_products` con `origen = 'real'` y los campos `sol`/`sclk`/`camera_eye` mapeados del nombre real (`ZL6`→`LEFT`, `ZR2`→`RIGHT`) — depende de T010 — hecho
- [x] T019 [P] [US2] Crear `tests/test_pds4_real_ingest.py` con un test del parseo del nombre real de producto (mapeo de cámara, extracción de sol y sclk), sin red real — hecho, **12 tests** tras el rediseño (parseo, listado de directorio por sol, checksum desde etiqueta PDS4, upsert/cuarentena con cursor simulado)
- [x] T020 [US2] Correr `ruff check ingestion/pds4_real_ingest.py tests/test_pds4_real_ingest.py` y `pytest tests/test_pds4_real_ingest.py -v` — deben pasar en verde (depende de T015-T019) — **12 passed**, `ruff` limpio. Suite completa del repo: **110 passed**. Dos bugs reales encontrados corriendo contra la red real y los tests, no por lectura de código: (1) `download_and_validate` importaba `requests` incondicionalmente aunque ya recibiera una sesión simulada — corregido para importar solo cuando `session is None`; (2) **el diseño basado en `collection_data_inventory.csv` como manifiesto con columnas de ruta/checksum era incorrecto** — se descubrió recién al correr el script contra la URL real (T021), devolvió un `ValueError` porque el CSV es un inventario PDS4 sin esas columnas. Rediseñado por completo (ver nota de T016 y research.md Decisión 2 revisada) antes de poder completar T021.
- [x] **Corrección adicional (2026-10-07, durante T021)**: la ingesta real sobre el sol 100 (152 productos) mostró el warning "sin `<md5_checksum>` reconocible" en el 100% de los productos, no solo en uno — se verificó con `WebFetch` directo contra 2 etiquetas de tipos de producto distintos (`102EDR`, `098ECM`) y contra el bundle completo (raíz y `data/`): **ninguna etiqueta de este bundle publica `<md5_checksum>` ni `<file_size>`**, y no existe manifiesto de checksums a ningún nivel. Solo traen `<msn_surface:telemetry_source_checksum>` (checksum de telemetría DSN, no de contenido). Se agregó `TruncatedDownloadError` en `ingestion/pds4_real_ingest.py`: cuando la etiqueta no trae checksum de contenido (el caso real de este bundle), se valida en su lugar integridad de transporte (bytes recibidos vs. header `Content-Length`), con el mismo tratamiento de cuarentena. FR-003/FR-004/SC-002 de `spec.md` y la tabla de `data-model.md` se actualizaron para reflejar esto explícitamente. Ver research.md, Decisión 2 (segunda corrección). `ruff` limpio, **13 passed** en `test_pds4_real_ingest.py` (12 + 1 nuevo test de truncamiento), suite completa: **111 passed**.
- [x] **Corrección adicional #2 (2026-10-07, durante T021)**: la corrida real terminó con solo **76 filas `origen='real'`** en RDS, exactamente la mitad de los 152 "productos" que el script dijo haber encontrado — confirmado con `psql` directo contra RDS. Se verificó con `WebFetch` contra el listado HTML real del servidor: cada archivo trae **dos** `<a href>` (uno para el ícono, otro para el nombre), ambos al mismo `.IMG` — el regex de `list_sol_products` los contaba dos veces. No duplicó filas (protegido por `ON CONFLICT (product_id) DO NOTHING`, FR-007), pero sí duplicaba innecesariamente descargas y `put_object` a S3. Corregido deduplicando por nombre de archivo en `list_sol_products`. Test fixture actualizado para reproducir la estructura real (ícono + nombre). `ruff` limpio, **13 passed**, suite completa: **111 passed**.
- [x] Agregar `requests>=2.31.0` a `ingestion/requirements.txt` (no estaba, y el script lo necesita)
- [x] Agregar `ingestion` a `tests/conftest.py` para que `pytest` pueda importar `pds4_real_ingest` (antes solo `airflow/plugins`, `simulator`, `common`)
- [x] T021 [US2] Con EC2 y RDS encendidos: ejecutar `ingestion/pds4_real_ingest.py` contra el bundle real una vez, y verificar con `SELECT origen, count(*) FROM image_products GROUP BY origen;` que aparece la fila `real` (quickstart.md, sección 2.4) — hecho 2026-10-07: `real | 76` en RDS (sol 100), verificado con `psql` directo (no hay contenedor `postgres` local en este stack, es RDS). 76 = cantidad correcta de productos distintos tras el fix de deduplicación (ver nota arriba); no hay filas `simulado` porque `rover_simulator`/`dsn_receiver` están `Exited (137)` (posible OOM del t3.small) desde antes de esta corrida — no es un defecto de esta feature, queda para investigar aparte.
- [x] T022 [US2] Repetir la misma ejecución sobre el mismo subconjunto y confirmar que el conteo de `origen = 'real'` no cambia (idempotencia, FR-007, SC-003, quickstart.md sección 2.5) — hecho 2026-10-07: segunda corrida (ya con el fix de deduplicación) terminó y el conteo en RDS siguió exacto en `real | 76`, sin duplicados ni cambios. FR-007/SC-003 verificados contra AWS real.

**Checkpoint**: Escenario 2 completo — productos reales en Raw, marcados, sin duplicados en re-ejecución.

---

## Fase 5: Escenario 3 — PySpark en Glue vs SQL (Prioridad: P2)

**Meta**: el job de Glue reproduce `science.sol_filter_coverage` sobre el mismo origen, y se compara fila por fila (spec.md, Escenario 3).

**Prueba independiente**: ejecutar job y vista SQL sobre el mismo subconjunto y comparar.

**Requiere RDS encendido en T028-T031** — T023-T026 son cambios de código/infra que se revisan con el plan, sin aplicar todavía.

- [x] T023 [P] [US3] Agregar `aws_glue_connection` (tipo JDBC hacia `aws_db_instance.rover_mars`) en `infra/aws/glue_job.tf` (nuevo archivo, research.md Decisión 3) — hecho 2026-10-07, incluye el security group `glue_jdbc` con la regla auto-referenciada que AWS exige para conexiones JDBC de Glue en VPC
- [x] T024 [US3] Agregar una regla de ingreso en `aws_security_group.rds` que acepte conexiones desde el security group de la conexión Glue (depende de T023) — `aws_security_group_rule.rds_from_glue` en `infra/aws/glue_job.tf`, sin tocar `rds.tf`
- [x] T025 [US3] Agregar el recurso `aws_glue_job` en `infra/aws/glue_job.tf`, apuntando al script de T026 (depende de T023) — incluye `aws_s3_object` que sube el script a S3 (si no, `script_location` apuntaría a una clave inexistente), rol IAM dedicado (`glue_job`, separado del rol del crawler) y `glue_version = "4.0"`
- [x] T026 [P] [US3] Crear `infra/aws/glue/sol_filter_coverage_job.py`: PySpark que lee `image_products` por JDBC (vía la conexión nombrada de Glue, sin credenciales en el script) y calcula `sol, n_images, n_left, n_right, n_filters` agrupado por sol, cumpliendo exactamente el esquema de `contracts/cobertura_sol_schema.md` — hecho; `ruff check` pasa. **No se puede probar localmente**: los imports `awsglue.*` solo existen en el runtime de Glue, no en un `pip install pyspark` normal — su verificación real es T029/T030, con RDS encendido
- [x] T027 [US3] Correr `terraform fmt`/`validate`/`plan` en `infra/aws/` y revisar que solo aparecen los recursos de T023-T025 antes de aplicar (depende de T023-T026) — hecho. **Dos hallazgos reales de `terraform validate`**: (1) `aws_security_group_rule.rds_from_glue` y el SG `glue_jdbc` tenían tildes/em-dash en su `description`, que AWS rechaza (`^[0-9A-Za-z_ .:/()#,@\[\]+=&;{}!$*-]*$`) — corregido a ASCII plano. `terraform plan` (sin `-out`, sin aplicar): **`Plan: 9 to add, 1 to change, 0 to destroy`** — los 9 son exactamente los de T023-T025; el "1 to change" es `aws_db_instance.rover_mars.password`, un artefacto de haber usado una contraseña de prueba en esta sesión (no tengo la real) — **con la contraseña real exportada, ese cambio debería desaparecer**; si no desaparece, investigar antes de aplicar
- [x] T028 [US3] Con RDS encendido: `terraform apply` del plan revisado en T027 — hecho 2026-10-07: `Apply complete! Resources: 9 added, 0 changed, 0 destroyed`, exacto al plan de T027 (el "1 to change" del password del dry-run anterior desapareció al usar la contraseña real, confirmando que era un artefacto de la contraseña de prueba)
- [x] T029 [US3] Ejecutar el job de Glue sobre el mismo subconjunto de sols usado en US2 (depende de T021, T028) — hecho 2026-10-07: `JobRunState: SUCCEEDED` (run `jr_ad34054d...`). Dos hallazgos reales antes de lograrlo, ambos con `terraform apply` separado: (1) el job falló con "VPC S3 endpoint validation failed" — un job de Glue en VPC necesita ruta a S3; se agregó `aws_vpc_endpoint.s3` tipo Gateway (sin costo) en `network.tf`; (2) al agregar ese endpoint, `terraform plan` mostró que iba a **destruir** la regla de ingreso de Glue hacia RDS — `aws_security_group.rds` usa bloques `ingress {}` inline, y mezclarlos con el `aws_security_group_rule` separado de T023/T024 hacía que Terraform compitiera por el control del set de reglas; se migró la regla al bloque inline en `rds.tf` y se usó `terraform state rm` (no destroy) para no revocar la regla real durante la migración
- [x] **Incidente de seguridad (2026-10-07, fuera del flujo de T029/T030, Principio V)**: un commit de rutina (`3f94563`) subió por accidente `infra/aws/terraform.tfstate.*.backup` al repo público — generado por `terraform state rm` (migración de T029) y no cubierto por el `.gitignore` (que solo tenía el patrón literal `terraform.tfstate.backup`, sin wildcard para la variante con timestamp). Ese archivo contenía la contraseña maestra de RDS en texto plano. Acciones: (1) archivo removido del árbol y `.gitignore` corregido con patrón wildcard (commit `253399a`); (2) contraseña **rotada en AWS real** (RDS + conexión JDBC de Glue) vía `terraform apply` con `apply_immediately = true` (agregado a `rds.tf`, commit `4701078`, necesario porque sin eso el cambio de password queda en cola para la próxima ventana de mantenimiento); (3) `.env` del EC2 actualizado y `airflow_scheduler`/`airflow_webserver` reiniciados con la contraseña nueva, verificado sin errores de conexión en los logs. **No** se purgó (todavía) el blob del commit viejo del historial de git — queda pendiente, es secundario a la rotación (que es lo que de verdad neutraliza la exposición en un repo ya público). Dos intentos de rotación fallaron antes del exitoso: uno por `openssl rand -base64` generando un `/` (RDS rechaza `/`, `@`, `"` y espacio en el password — se cambió a `openssl rand -hex`), y uno por la contraseña exportada en una pestaña de terminal distinta a la que corría los comandos siguientes (variable de entorno no persiste entre sesiones de shell) — resuelto con un único script que genera, aplica y envía el valor en un solo proceso, sin puntos de corte entre pasos.
- [x] T030 [US3] Comparar la salida del job contra `SELECT sol, n_images, n_left, n_right, n_filters FROM science.sol_filter_coverage WHERE sol IN (...)` y confirmar coincidencia fila por fila (SC-004, contracts/cobertura_sol_schema.md) — hecho 2026-10-07: ambos caminos dan `100, 76, 38, 38, 0` exacto, columna por columna, para sol=100. El job de Glue se leyó del CSV real en `s3://rovermars-gold-demo/glue-job-output/sol_filter_coverage/`, la vista SQL directo de RDS vía `psql`. `n_filters=0` en ambos por igual (la ingesta real no completa `filter_wavelength_nm`, `COUNT(DISTINCT ...)` de solo NULL da 0 en SQL y en Spark por igual) — SC-004 verificado contra AWS real, no con datos de prueba
- [x] T031 [US3] Medir tiempo y costo de ambos caminos (SQL vs Glue) para alimentar el ADR-023 — hecho 2026-10-07, datos reales vía `aws glue get-job-run`: job de Glue (`jr_ad34054d...`) tardó **101s** de pared, **203 DPU-segundos** (2 workers G.1X), costo real ≈ 203/3600 × $0.44/DPU-hora ≈ **$0.025 por corrida**, casi toda esa duración es arranque en frío del clúster, no cómputo (76 filas no toman 101s de procesamiento real). La vista SQL respondió instantánea (sub-segundo, `psql` sin demora perceptible) y sin costo incremental (ya corre dentro del cómputo reservado de RDS). Conclusión para el ADR-023: a este volumen, Spark/Glue no se justifica frente a SQL — el overhead de aprovisionar el clúster domina por completo sobre el trabajo real a este tamaño de datos

**Checkpoint**: Escenario 3 completo — comparación objetiva disponible para decidir si Spark se justifica.

---

## Fase 6: Escenario 4 — Visibilidad y alertas (Prioridad: P3)

**Meta**: alerta ante anomalía y dashboard público de solo lectura (spec.md, Escenario 4).

**Prueba independiente**: forzar una lectura fuera de umbral y verificar que llega la alerta; abrir el dashboard sin credenciales de escritura.

- [ ] T032 [P] [US4] Verificar si `detect_anomalies`/`build_gold_aggregates` ya publican al tópico SNS `rovermars-pipeline-alerts`; si no, agregar la publicación en el paso correspondiente de `airflow/dags/meda_pipeline.py` — **revisado 2026-10-07 (solo lectura de código, sin infra encendida)**: no está implementado. `mastcamz_pipeline.py:459` tiene un comentario `# En AWS: publicar a SNS (ver ADR-016) — pendiente` — es código nuevo a escribir, no algo que ya exista. Queda pendiente para una sesión futura con AWS encendido
- [ ] T033 [US4] Con el stack corriendo, forzar una lectura fuera de umbral (usar los `MEDA_*` de demo ya documentados) y confirmar que llega el correo de alerta a la suscripción SNS ya confirmada — **pendiente**: requiere EC2/RDS/SNS encendidos; la infraestructura ya se destruyó en T013 (decisión deliberada, ver quickstart.md anexo) antes de poder validar esto. Depende de T032 (publicación a SNS) primero
- [ ] T034 [US4] Confirmar que `dashboard_cloudfront_domain` es accesible de solo lectura, sin credenciales de escritura — **pendiente**: la distribución CloudFront ya fue destruida en T013, no hay URL viva para probar en esta ventana

**Nota (2026-10-07)**: T032-T034 (Escenario 4, prioridad P3 — la de menor prioridad de
la spec) quedan sin cerrar en esta iteración porque la infraestructura se destruyó
deliberadamente al terminar los Escenarios 1-3 (P1/P1/P2), para no mantener cómputo
encendido sin necesidad (Principio VI). Cerrarlos requiere: implementar la
publicación a SNS (T032, código nuevo), y una ventana nueva de AWS encendido para
T033/T034. No bloquea el cierre de esta feature para portafolio — P1/P1/P2 ya están
demostrados contra AWS real de punta a punta.

**Checkpoint**: los 4 escenarios de spec.md quedan cubiertos.

---

## Fase 7: Pulido — ADRs y CI (transversal)

**Propósito**: Principio VII (ADR para toda decisión no trivial) y Principio VIII (CI como guardián).

- [x] T035 [P] Redactar ADR-021 en `docs/ANALISIS_MODERN_DATA_STACK.md`: `IamAwsProvider` vs reescribir a `boto3` (research.md, Decisión 1) — hecho 2026-10-07, incluye los hallazgos reales del hop limit de IMDS y de la imagen de Airflow sin reconstruir
- [x] T036 [P] Redactar ADR-022 en `docs/ANALISIS_MODERN_DATA_STACK.md`: fuente real `mastcamz_ops_raw` vs `sci_calibrated` (research.md, Decisión 2) — hecho 2026-10-07, incluye los 3 hallazgos reales (manifiesto sin rutas, sin checksum de contenido, listado HTTP duplicado)
- [x] T037 [P] Redactar ADR-023 en `docs/ANALISIS_MODERN_DATA_STACK.md`: Glue Job vía JDBC vs EMR/Spark local, con los números medidos en T031 (research.md, Decisión 3) — hecho 2026-10-07, con la conclusión medida (Spark no se justifica a este volumen) y los 2 hallazgos de infraestructura (VPC endpoint de S3, conflicto de security group rules)
- [x] T038 Correr los 4 workflows de CI (`lint.yml`, `test.yml`, `dbt-ci.yml`, `docker-build.yml`) en verde antes de mergear la rama `002-aws-deployment` (Principio VIII) — hecho 2026-10-07. Los 4 workflows solo disparan en push a `main` o en Pull Request, no en push directo a una rama de feature — se abrió el PR #5 (`002-aws-deployment` → `main`) para dispararlos. Resultado: **los 9 checks en verde** (`ruff`, `pytest`, `dbt-build`, `build-images` ×3, `Analyze` ×2, `CodeQL`)
- [x] T039 Actualizar `README.md`/`README.fr.md`/`README.es.md` si el flujo de datos visible cambió con esta feature (Restricciones de Presentación de la constitución) — hecho 2026-10-07. Los 3 README tenían "Real PDS4 data ingestion" listado en *Future Extensions* (y su equivalente FR/ES) — ya no es futuro, se movió a una nota en la sección RAW Layer explicando la convivencia real/simulado vía la columna `origen`, y se quitó de la lista de extensiones futuras en los 3 idiomas

---

## Dependencias y Orden de Ejecución

### Dependencias de fase

- **Fase 1 (Setup)**: ya completa — no bloquea nada nuevo.
- **Fase 2 (Fundacional)**: bloquea Fase 3 (parcialmente, vía T011) y toda la Fase 4. No requiere AWS encendido.
- **Fase 3 (US1-cierre)**: sus tareas T011-T014 se ejecutan **al final**, después de Fase 4 y Fase 5 (necesita datos reales y el job de Glue para la "corrida completa").
- **Fase 4 (US2)**: depende de Fase 2. T015-T020 son locales; T021-T022 requieren EC2+RDS encendidos.
- **Fase 5 (US3)**: T023-T026 no dependen de Fase 4 y pueden adelantarse en paralelo. T027 es revisión local. T028-T031 requieren RDS encendido, y T029 usa el subconjunto que T021 ya cargó.
- **Fase 6 (US4)**: independiente de Fase 4/5 — puede hacerse en cualquier momento con el stack corriendo.
- **Fase 7 (Pulido)**: depende de que las decisiones de Fases 2, 4 y 5 estén implementadas (para documentar con datos reales, no antes).

### Única ventana con EC2/RDS encendidos (recomendado)

Para minimizar el tiempo de infraestructura encendida (ver `quickstart.md`), agrupar en una sola sesión: T011, T021, T022, T028, T029, T030, T012, T013. Todo lo demás (T006-T010, T015-T020, T023-T027, T032, T035-T039) se hace con la infraestructura apagada.

---

## Ejemplo de ejecución en paralelo

```bash
# Fase 2 — en paralelo, son archivos distintos:
Task: "T006 Modificar common/rovermars_common/storage.py (IamAwsProvider)"
Task: "T007 Agregar test en tests/test_storage.py"
Task: "T010 ALTER TABLE en database/schema.sql"

# Fase 5 — T023 y T026 no dependen entre sí:
Task: "T023 aws_glue_connection en infra/aws/glue_job.tf"
Task: "T026 infra/aws/glue/sol_filter_coverage_job.py"
```

---

## Estrategia de Implementación

### Primero lo bloqueante

1. Completar Fase 2 (Fundacional) — sin esto nada de lo nuevo corre contra AWS real.
2. Completar Fase 4 (US2) en local (T015-T020) antes de encender nada.
3. Completar Fase 5 en local (T023-T027) antes de encender nada.
4. Encender EC2 + RDS **una sola vez** y correr, en orden: T021, T022, T028, T029, T030, T011, T012, T013.
5. Fase 6 (US4) y Fase 7 (ADRs, CI) pueden ir en paralelo con lo anterior o después, sin requerir una segunda ventana de infraestructura encendida.

### Entrega incremental

- Fundacional listo → US2 puede empezar.
- US2 completo (sin encender AWS) → listo para la ventana real.
- US3 completo (sin encender AWS) → listo para la misma ventana real.
- Una ventana real cubre US1-cierre + US2 (validación) + US3 (validación) de punta a punta.
- US4 y Fase 7 no bloquean el cierre de la demo.

---

## Notas

- Los `[P]` son archivos distintos sin dependencias entre sí.
- Las tareas de Fase 1 están marcadas `[x]` porque ya se ejecutaron contra AWS real en esta sesión (2026-10-06/07) — no son trabajo pendiente.
- Verificar que T008/T009 (ruff/pytest) fallan antes de T006/T007 no aplica aquí: son tests nuevos sobre código que se modifica en la misma tarea, no TDD estricto — ya se seguía esta convención en `tests/test_storage.py` existente.
- Evitar: encender EC2/RDS para una sola tarea aislada cuando se puede agrupar con otras (ver "Única ventana con EC2/RDS encendidos").
