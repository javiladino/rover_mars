# ADR-015 — Glue Data Catalog + Athena: capa serverless de consulta SQL
# sobre la capa Gold en S3 (Parquet particionado por sol). Ver
# docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md — Fase 4 para el cambio en
# build_gold_aggregates que escribe Parquet además del JSON actual.

resource "aws_glue_catalog_database" "rover_mars" {
  name = "${var.project_prefix}_gold"
}

resource "aws_iam_role" "glue_crawler" {
  name = "${var.project_prefix}-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_read" {
  name = "${var.project_prefix}-glue-s3-read"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.data_lake["gold"].arn, "${aws_s3_bucket.data_lake["gold"].arn}/*"]
    }]
  })
}

resource "aws_glue_crawler" "gold_parquet" {
  name          = "${var.project_prefix}-gold-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.rover_mars.name
  # Se ejecuta manualmente o vía Airflow (no se agenda automático para no
  # gastar crédito sin uso — ver ADR-020).
  schedule = null

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake["gold"].bucket}/parquet/"
  }
}

resource "aws_athena_workgroup" "rover_mars" {
  name = "${var.project_prefix}-workgroup"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake["gold"].bucket}/athena-results/"
    }
  }
}
