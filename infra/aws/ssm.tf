# ADR-017 — SSM Parameter Store (tier estándar, gratis) para credenciales.
# Los VALORES no se fijan aquí en texto plano: se crean como placeholders
# "changeme" y se actualizan manualmente después de `terraform apply` con:
#   aws ssm put-parameter --name /rovermars/postgres_password --value "..." \
#     --type SecureString --overwrite
# Terraform gestiona la existencia y el tipo del parámetro, no su secreto real.

locals {
  ssm_parameters = [
    "postgres_password",
    "minio_secret_key",
    "airflow_fernet_key",
    "grafana_admin_password",
  ]
}

resource "aws_ssm_parameter" "secrets" {
  for_each = toset(local.ssm_parameters)

  name        = "/${var.project_prefix}/${each.key}"
  description = "Gestionado manualmente post-apply — Terraform solo reserva el nombre/tipo (ADR-017)"
  type        = "SecureString"
  value       = "changeme"

  lifecycle {
    ignore_changes = [value] # evita que `terraform apply` pise el valor real ya rotado a mano
  }
}
