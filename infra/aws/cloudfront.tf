# ADR-018 — Publicación de dashboard/index.html vía S3 + CloudFront.
# Siempre disponible y de costo casi nulo, no depende de que el EC2 (ADR-014)
# esté encendido. Subir el HTML con:
#   aws s3 sync ../../dashboard s3://<bucket>/ --exclude "*" --include "index.html"

resource "aws_s3_bucket" "dashboard_site" {
  bucket = "${var.project_prefix}-dashboard-${var.environment}"
}

resource "aws_s3_bucket_public_access_block" "dashboard_site" {
  bucket                  = aws_s3_bucket.dashboard_site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${var.project_prefix}-dashboard-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "dashboard" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # solo edges NA/EU — el más barato

  origin {
    domain_name              = aws_s3_bucket.dashboard_site.bucket_regional_domain_name
    origin_id                = "s3-dashboard"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "s3-dashboard"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "dashboard_cloudfront_read" {
  bucket = aws_s3_bucket.dashboard_site.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.dashboard_site.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.dashboard.arn
        }
      }
    }]
  })
}
