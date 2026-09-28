variable "aws_region" {
  description = "Región AWS de despliegue"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Nombre del entorno (demo, dev, etc.)"
  type        = string
  default     = "demo"
}

variable "project_prefix" {
  description = "Prefijo para nombrar todos los recursos (buckets, roles, etc.)"
  type        = string
  default     = "rovermars"
}

variable "budget_monthly_limit_usd" {
  description = "Límite mensual (USD) para la alarma de AWS Budgets (ADR-020)"
  type        = number
  default     = 40
}

variable "budget_alert_email" {
  description = "Correo que recibe las alertas de AWS Budgets al 50%/80% del límite"
  type        = string
}

variable "ec2_instance_type" {
  description = "Tipo de instancia EC2 para Airflow+Kafka self-managed (ADR-014)"
  type        = string
  default     = "t3.small"
}

variable "ec2_key_pair_name" {
  description = "Nombre de un Key Pair EC2 ya existente en la cuenta, para acceso SSH"
  type        = string
}

variable "ssh_allowed_cidr" {
  description = "CIDR permitido para SSH al EC2 (restringir a tu IP en producción, ej. 1.2.3.4/32)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "rds_instance_class" {
  description = "Clase de instancia RDS (ADR-013). db.t3.micro cae en el free tier de 12 meses."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_master_password" {
  description = "Password del usuario maestro de RDS. No pasar por CLI en texto plano: usar TF_VAR_rds_master_password o un .tfvars no versionado."
  type        = string
  sensitive   = true
}

variable "sns_alert_email" {
  description = "Correo que recibe las alertas de anomalías del pipeline (ADR-016)"
  type        = string
}
