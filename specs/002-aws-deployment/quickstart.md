# Fase 1 — Guía de Validación: Despliegue Híbrido en AWS con Datos Reales

**Feature**: 002-aws-deployment · **Fecha**: 2026-10-07

Cada paso indica si necesita el EC2/RDS **encendidos** o si es trabajo que
se puede hacer con la infraestructura **apagada** (el estado en que quedó
al cierre de la sesión anterior: `stopped`, no terminada). El objetivo es
no prender el servidor antes de lo necesario.

---

## 1. Cliente de almacenamiento (`IamAwsProvider`)

**Infraestructura requerida**: apagada para desarrollar y testear en local;
**encendida** solo para la validación final contra S3 real.

1. Implementar el cambio en `common/rovermars_common/storage.py` (Decisión 1
   de `research.md`).
2. Agregar en `tests/test_storage.py` un test que verifique que, con
   `secure=True` y sin `access_key`/`secret_key`, el cliente se construye
   con `IamAwsProvider` (mockeando `minio.credentials.IamAwsProvider`, sin
   red real).
3. Correr, con el runtime real del proyecto (Python 3.11, igual que
   `python:3.11-slim`):
   ```bash
   ruff check common/ tests/test_storage.py
   pytest tests/test_storage.py -v
   ```
4. **Validación contra AWS real** (acá sí hace falta encender el EC2):
   arrancar la instancia, hacer `git pull`, y disparar manualmente
   `build_gold_aggregates` o una ejecución completa de `meda_full_pipeline`
   / `mastcamz_full_pipeline`. Resultado esperado: sin `AccessDenied` en los
   logs.

## 2. Ingesta de productos reales PDS4

**Infraestructura requerida**: el script de descarga puede probarse desde
cualquier máquina con salida a internet (no requiere el EC2 encendido). La
escritura a S3 y Postgres sí requiere el EC2 (por el rol IAM) y el RDS
encendidos.

1. Descargar una vez `collection_data_inventory.csv` del bundle
   `mastcamz_ops_raw` (ver `research.md`, Decisión 2) y filtrar un
   subconjunto acotado (1-2 sols).
2. Para cada producto del subconjunto: descargar `.IMG` + `.xml`, verificar
   checksum contra el manifiesto, subir a `raw` con el `product_id` real.
3. Insertar en `image_products` con `origen = 'real'` (ver `data-model.md`).
4. Verificación (requiere RDS encendido):
   ```sql
   SELECT origen, count(*) FROM image_products GROUP BY origen;
   ```
   Resultado esperado: una fila `real` con el conteo del subconjunto
   descargado, y las filas `simulado` existentes sin tocar.
5. Repetir el paso de ingesta sobre el mismo subconjunto y volver a correr
   la consulta anterior — el conteo de `real` no debe cambiar (FR-007,
   idempotencia).

## 3. Job PySpark en AWS Glue

**Infraestructura requerida**: **encendida** (RDS) para correr el job —
Glue necesita conectarse por JDBC a la base. El `terraform plan` que agrega
el `aws_glue_job` y la conexión puede revisarse con el RDS apagado, pero
`terraform apply` y la ejecución del job sí lo necesitan arriba.

1. Aplicar los recursos Terraform nuevos (`aws_glue_connection`,
   `aws_glue_job`, regla de ingreso en `aws_security_group.rds`) — revisar
   el plan antes de aplicar, como en el resto de la spec.
2. Ejecutar el job de Glue sobre el mismo subconjunto de sols usado en la
   ingesta real.
3. Comparar la salida contra:
   ```sql
   SELECT sol, n_images, n_left, n_right, n_filters
   FROM science.sol_filter_coverage
   WHERE sol IN (<sols del subconjunto>);
   ```
4. Verificación (SC-004): las filas coinciden exactamente, columna por
   columna, entre el job y la vista SQL — ver `contracts/cobertura_sol_schema.md`.
5. Registrar en el ADR correspondiente el tiempo y costo de ambos caminos,
   y la conclusión sobre si Spark se justifica para este volumen.

---

## Orden recomendado para minimizar tiempo de infraestructura encendida

1. Hacer **todo** el punto 1 (cliente de almacenamiento) y el desarrollo
   del punto 2 (script de descarga) con la infraestructura apagada.
2. Encender EC2 + RDS una sola vez.
3. Correr, en la misma ventana: la validación final del punto 1, la ingesta
   real del punto 2, y el `apply` + ejecución del punto 3.
4. Capturar evidencia (Escenario 1 de `spec.md`: facturación + corrida
   completa).
5. Apagar o destruir según corresponda al cierre de la demo.
