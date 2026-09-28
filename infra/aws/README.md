# infra/aws — Terraform (ADR-011 a ADR-020)

Provisiona la variante de despliegue en AWS descrita en
`docs/ANALISIS_MODERN_DATA_STACK.md` (sección 6) y ejecutada paso a paso en
`docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md` (Fase 4).

**No se ejecuta automáticamente.** Gasta crédito real de AWS — revisar
siempre `terraform plan` antes de `terraform apply`.

## Qué crea

| Archivo | Recursos | ADR |
|---|---|---|
| `s3.tf` | 4 buckets del data lake (raw/bronze/silver/gold) | ADR-012 |
| `rds.tf` + `network.tf` | RDS PostgreSQL 16 (PostGIS se activa a mano) | ADR-013 |
| `ec2.tf` + `iam.tf` | EC2 con Docker preinstalado, rol IAM de mínimo privilegio | ADR-014, ADR-017 |
| `ssm.tf` | Placeholders de parámetros en SSM Parameter Store | ADR-017 |
| `lambda.tf` + `lambda/` | Lambda disparada por `ObjectCreated` en el bucket `raw` | ADR-016 |
| `sns.tf` | Tópico SNS + suscripción por email para alertas | ADR-016 |
| `glue_athena.tf` | Glue Data Catalog + Crawler + Athena Workgroup | ADR-015 |
| `cloudfront.tf` | Bucket + distribución CloudFront para `dashboard/index.html` | ADR-018 |
| `budgets.tf` | AWS Budgets con alertas al 50/80/100% | ADR-020 |

## Uso

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars   # completar valores
export TF_VAR_rds_master_password="una-contraseña-fuerte"

terraform init
terraform apply -target=aws_budgets_budget.monthly   # primero el guardrail de gasto (ADR-020)
terraform plan                                        # revisar TODO el resto antes de aplicar
terraform apply
```

Al terminar: `terraform output` entrega la IP del EC2, el endpoint de RDS,
los nombres de bucket y la URL de CloudFront — todos estos valores van al
`.env` del EC2 (ver `.env.example` en la raíz del repo y
`docker-compose.aws.yml`).

Para liberar recursos y dejar de gastar crédito:

```bash
terraform destroy
```
