# ADR-017 — Rol IAM del EC2: permisos acotados de lectura a SSM Parameter Store
# y lectura/escritura a los buckets del data lake (ADR-012). Nada de "*:*".

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "ec2_app" {
  name = "${var.project_prefix}-ec2-app-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ec2_s3_access" {
  name = "${var.project_prefix}-ec2-s3-access"
  role = aws_iam_role.ec2_app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
        Resource = concat(
          [for b in aws_s3_bucket.data_lake : b.arn],
          [for b in aws_s3_bucket.data_lake : "${b.arn}/*"],
        )
      }
    ]
  })
}

resource "aws_iam_role_policy" "ec2_ssm_read" {
  name = "${var.project_prefix}-ec2-ssm-read"
  role = aws_iam_role.ec2_app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParametersByPath"]
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_prefix}/*"
    }]
  })
}

resource "aws_iam_role_policy" "ec2_sns_publish" {
  name = "${var.project_prefix}-ec2-sns-publish"
  role = aws_iam_role.ec2_app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = aws_sns_topic.pipeline_alerts.arn
    }]
  })
}

resource "aws_iam_instance_profile" "ec2_app" {
  name = "${var.project_prefix}-ec2-app-profile"
  role = aws_iam_role.ec2_app.name
}
