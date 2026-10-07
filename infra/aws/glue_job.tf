# ADR-023 — Job PySpark en AWS Glue, vía JDBC contra RDS (no EMR, no un S3
# "Bronze/Silver" paralelo) — ver specs/002-aws-deployment/research.md,
# Decisión 3. Compara contra science.sol_filter_coverage (database/schema.sql)
# sobre la MISMA tabla image_products, para que cualquier diferencia de
# resultado sea un bug real, no un artefacto de datos distintos.
#
# No se agenda ni se ejecuta automáticamente (igual que aws_glue_crawler.gold_parquet)
# — se dispara a mano o desde Airflow, solo durante la ventana de validación
# con RDS encendido (ver quickstart.md).

data "aws_subnet" "glue_jdbc" {
  id = data.aws_subnets.default.ids[0]
}

# Requisito documentado de AWS Glue para conexiones JDBC en VPC: el security
# group de la conexión necesita una regla de ingreso auto-referenciada (todo
# el tráfico TCP), porque los ejecutores de Spark dentro del job se comunican
# entre sí usando este mismo security group.
resource "aws_security_group" "glue_jdbc" {
  name        = "${var.project_prefix}-glue-jdbc-sg"
  description = "SG de la conexion JDBC de Glue hacia RDS - requiere regla auto-referenciada"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group_rule" "glue_jdbc_self_reference" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  security_group_id        = aws_security_group.glue_jdbc.id
  source_security_group_id = aws_security_group.glue_jdbc.id
}

# RDS acepta conexiones del SG de Glue además del EC2 de Airflow (ver rds.tf,
# que ya tiene la regla hacia aws_security_group.ec2_app).
resource "aws_security_group_rule" "rds_from_glue" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = aws_security_group.glue_jdbc.id
  description              = "Postgres desde la conexion JDBC de Glue"
}

resource "aws_glue_connection" "rds_jdbc" {
  name            = "${var.project_prefix}-rds-jdbc"
  connection_type = "JDBC"

  connection_properties = {
    JDBC_CONNECTION_URL = "jdbc:postgresql://${aws_db_instance.rover_mars.endpoint}/rover_mars"
    USERNAME            = "rover"
    PASSWORD            = var.rds_master_password
  }

  physical_connection_requirements {
    availability_zone      = data.aws_subnet.glue_jdbc.availability_zone
    subnet_id              = data.aws_subnet.glue_jdbc.id
    security_group_id_list = [aws_security_group.glue_jdbc.id]
  }
}

resource "aws_iam_role" "glue_job" {
  name = "${var.project_prefix}-glue-job-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_job_service" {
  role       = aws_iam_role.glue_job.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_job_s3_script" {
  name = "${var.project_prefix}-glue-job-s3-script"
  role = aws_iam_role.glue_job.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.data_lake["gold"].arn, "${aws_s3_bucket.data_lake["gold"].arn}/*"]
    }]
  })
}

resource "aws_s3_object" "sol_filter_coverage_script" {
  bucket = aws_s3_bucket.data_lake["gold"].id
  key    = "glue-scripts/sol_filter_coverage_job.py"
  source = "${path.module}/glue/sol_filter_coverage_job.py"
  etag   = filemd5("${path.module}/glue/sol_filter_coverage_job.py")
}

resource "aws_glue_job" "sol_filter_coverage" {
  name     = "${var.project_prefix}-sol-filter-coverage"
  role_arn = aws_iam_role.glue_job.arn

  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2

  connections = [aws_glue_connection.rds_jdbc.name]

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake["gold"].bucket}/${aws_s3_object.sol_filter_coverage_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--output_s3_path" = "s3://${aws_s3_bucket.data_lake["gold"].bucket}/glue-job-output/sol_filter_coverage/"
    "--job-language"   = "python"
  }

  # No se agenda — se dispara a mano durante la ventana de validación
  # (ver quickstart.md, "Única ventana con EC2/RDS encendidos").
}
