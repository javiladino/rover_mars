# ADR-012 — Amazon S3 como data lake (reemplazo/complemento de MinIO)

locals {
  data_lake_layers = ["raw", "bronze", "silver", "gold"]
}

resource "aws_s3_bucket" "data_lake" {
  for_each = toset(local.data_lake_layers)
  bucket   = "${var.project_prefix}-${each.key}-${var.environment}"
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  for_each = aws_s3_bucket.data_lake

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data_lake" {
  for_each = aws_s3_bucket.data_lake

  bucket = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Lifecycle: abaratar aún más el free tier moviendo objetos raw/bronze
# antiguos a Standard-IA tras 30 días (Silver/Gold se consultan más seguido).
resource "aws_s3_bucket_lifecycle_configuration" "raw_bronze_ia" {
  for_each = toset(["raw", "bronze"])

  bucket = aws_s3_bucket.data_lake[each.key].id
  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}
