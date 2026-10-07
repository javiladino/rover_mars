# Evidencia de Costo — Despliegue 002-aws-deployment

**Feature**: 002-aws-deployment · **Capturado**: 2026-10-07, con la infraestructura
AWS (EC2 `t3.small` + RDS `db.t3.micro`) encendida durante la ventana de validación
de esta feature (Escenario 1, FR-009, SC-005, SC-007).

## AWS Budgets — gasto acumulado del mes

```
$ aws budgets describe-budgets --account-id <cuenta> --region us-east-1 \
    --query 'Budgets[].{Name:BudgetName,Limit:BudgetLimit.Amount,ActualSpend:CalculatedSpend.ActualSpend.Amount,ForecastedSpend:CalculatedSpend.ForecastedSpend.Amount}'
```

| Name                      | ActualSpend | ForecastedSpend | Limit |
| ------------------------- | ----------- | ---------------- | ----- |
| My Zero-Spend Budget      | 0.0         | 0.0               | 1.0   |
| rovermars-monthly-budget  | 0.0         | 0.0               | 40.0  |

**SC-001/SC-005**: las alertas de presupuesto (`rovermars-monthly-budget`, 50/80/100%)
ya existían antes de aplicar cualquier recurso de pago de esta feature (ver
`infra/aws/budgets.tf`, aplicado en una sesión anterior), y el gasto acumulado del
mes sigue en $0 contra el tope de $40.

## Cost Explorer — desglose por servicio (2026-10-01 a 2026-10-08)

```
$ aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-10-08 \
    --granularity MONTHLY --metrics UnblendedCost --group-by Type=DIMENSION,Key=SERVICE
```

| Servicio                                 | UnblendedCost (USD) |
| ----------------------------------------- | -------------------- |
| AWS Data Transfer                         | ~0 (crédito mínimo)  |
| AWS Glue                                  | 0                     |
| AWS Key Management Service                | 0                     |
| AWS Secrets Manager                       | 0                     |
| EC2 - Other                               | ~0                    |
| Amazon Elastic Compute Cloud - Compute     | 0                     |
| Amazon Relational Database Service         | ~0                    |
| Amazon Simple Notification Service        | 0                     |
| Amazon Simple Queue Service               | 0                     |
| Amazon Simple Storage Service              | ~0                    |
| Amazon Virtual Private Cloud               | 0                     |
| AmazonCloudWatch                          | 0                     |
| Tax                                        | 0                     |

**Nota honesta sobre el $0**: Cost Explorer tiene hasta ~24h de demora en reportar
uso reciente — el job de Glue corrido hoy (T029, 101s, ~$0.025 reales calculados vía
`aws glue get-job-run`/DPU-segundos, ver `tasks.md` T031) probablemente todavía no
se refleja acá. El resto del $0 es consistente con que esta cuenta corre bajo
restricciones de plan gratuito (ver `FreeTierRestrictionError` encontrado en una
sesión anterior al configurar `backup_retention_period` de RDS) — EC2 `t3.small` y
RDS `db.t3.micro` quedan dentro de elegibilidad de free tier para esta ventana corta
de uso. El costo real medido directamente (no vía Cost Explorer) está en `tasks.md`
T031: ~$0.025 por corrida de Glue, SQL sin costo incremental.

## Verificación de teardown (T013)

Pendiente — se completa después de este documento, inmediatamente antes de
`terraform destroy`, con `aws ec2 describe-instances` / `aws rds describe-db-instances`
confirmando que no quedan recursos de pago activos (FR-010, SC-006).
