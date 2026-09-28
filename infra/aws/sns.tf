# ADR-016 — SNS para alertas reales del pipeline (reemplaza el `log.info`
# de notify_science_team cuando el despliegue vive en AWS).

resource "aws_sns_topic" "pipeline_alerts" {
  name = "${var.project_prefix}-pipeline-alerts"
}

resource "aws_sns_topic_subscription" "pipeline_alerts_email" {
  topic_arn = aws_sns_topic.pipeline_alerts.arn
  protocol  = "email"
  endpoint  = var.sns_alert_email
}
