# Rover Mars — Infraestructura AWS (ADR-011 a ADR-020, docs/ANALISIS_MODERN_DATA_STACK.md)
#
# Este módulo NO se aplica automáticamente. Requiere `aws configure` con
# credenciales de la cuenta de crédito de estudiante y una revisión manual
# de `terraform plan` antes de `terraform apply` (gasta crédito real).
# Ver docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md — Fase 4.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Backend local por defecto (adecuado para un proyecto de portafolio de
  # una sola persona). Si se trabaja en equipo, migrar a un backend S3+DynamoDB.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "rover-mars"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
