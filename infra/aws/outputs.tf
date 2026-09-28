output "ec2_public_ip" {
  description = "IP pública del EC2 (Airflow/Kafka self-managed)"
  value       = aws_instance.app.public_ip
}

output "rds_endpoint" {
  description = "Endpoint de conexión de RDS PostgreSQL"
  value       = aws_db_instance.rover_mars.endpoint
  sensitive   = true
}

output "s3_buckets" {
  description = "Buckets del data lake (raw/bronze/silver/gold)"
  value       = { for k, b in aws_s3_bucket.data_lake : k => b.bucket }
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard_site.bucket
}

output "dashboard_cloudfront_domain" {
  description = "URL pública de la demo estática (dashboard/index.html)"
  value       = aws_cloudfront_distribution.dashboard.domain_name
}

output "sns_alerts_topic_arn" {
  value = aws_sns_topic.pipeline_alerts.arn
}

output "athena_workgroup" {
  value = aws_athena_workgroup.rover_mars.name
}

output "glue_database" {
  value = aws_glue_catalog_database.rover_mars.name
}
