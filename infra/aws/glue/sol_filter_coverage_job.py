"""
Job de AWS Glue (PySpark) que reproduce `science.sol_filter_coverage`
(database/schema.sql) leyendo `image_products` por la MISMA conexión JDBC
que usa el resto del proyecto -- no un S3 "Bronze/Silver" paralelo. Ver
specs/002-aws-deployment/research.md (Decisión 3) y
specs/002-aws-deployment/contracts/cobertura_sol_schema.md para el esquema
de salida que este job y la vista SQL DEBEN compartir exactamente.

Se dispara a mano durante la ventana de validación con RDS encendido (ver
quickstart.md, "Única ventana con EC2/RDS encendidos") -- no corre
agendado (ver infra/aws/glue_job.tf).

No se puede probar fuera del runtime de AWS Glue (los imports de
`awsglue.*` no existen en un `pip install pyspark` local) -- su
verificación real es la tarea T029/T030 de tasks.md, comparando la salida
contra la vista SQL con el servidor encendido.
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F

# Debe coincidir con el `name` de aws_glue_connection.rds_jdbc en glue_job.tf.
GLUE_CONNECTION_NAME = "rovermars-rds-jdbc"
SOURCE_TABLE = "image_products"


def compute_sol_coverage(df):
    """
    Agrupa por sol y calcula las mismas 5 columnas que
    `science.sol_filter_coverage` (ver contracts/cobertura_sol_schema.md):
    sol, n_images, n_left, n_right, n_filters.

    Separado de main() a propósito: la lógica de agregación queda en una
    sola función con una sola responsabilidad (Principio III), aparte de la
    configuración del job y la conexión JDBC.
    """
    return (
        df.groupBy("sol")
        .agg(
            F.count("*").alias("n_images"),
            F.sum(F.when(F.col("camera_eye") == "LEFT", 1).otherwise(0)).alias("n_left"),
            F.sum(F.when(F.col("camera_eye") == "RIGHT", 1).otherwise(0)).alias("n_right"),
            F.countDistinct("filter_wavelength_nm").alias("n_filters"),
        )
        .orderBy("sol")
    )


def main():
    args = getResolvedOptions(sys.argv, ["JOB_NAME", "output_s3_path"])

    spark_context = SparkContext()
    glue_context = GlueContext(spark_context)
    job = Job(glue_context)
    job.init(args["JOB_NAME"], args)

    dynamic_frame = glue_context.create_dynamic_frame.from_options(
        connection_type="postgresql",
        connection_options={
            "useConnectionProperties": "true",
            "connectionName": GLUE_CONNECTION_NAME,
            "dbtable": SOURCE_TABLE,
        },
    )
    df = dynamic_frame.toDF()

    cobertura = compute_sol_coverage(df)
    cobertura.show(50, truncate=False)

    (
        cobertura.coalesce(1)
        .write.mode("overwrite")
        .option("header", "true")
        .csv(args["output_s3_path"])
    )

    job.commit()


if __name__ == "__main__":
    main()
