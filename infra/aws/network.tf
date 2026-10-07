# Se reutiliza la VPC default de la cuenta (suficiente para un portafolio de
# una sola instancia). En un entorno de equipo real se crearía una VPC dedicada.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_db_subnet_group" "default" {
  name       = "${var.project_prefix}-rds-subnets"
  subnet_ids = data.aws_subnets.default.ids
}

# Requisito real descubierto corriendo el job de Glue (T029, 2026-10-07): un
# job de Glue en VPC necesita que su subred tenga ruta a S3 -- sin esto, el
# job falla con "VPC S3 endpoint validation failed" antes de ejecutar una
# sola línea de PySpark. Un Gateway Endpoint no tiene costo por hora (a
# diferencia de un NAT Gateway) -- la opción correcta para una demo acotada
# en costo (Principio VI). Se asocia a todas las route tables de la VPC
# default para cubrir cualquier subred que Glue use, no solo la primera.
data "aws_route_tables" "default" {
  vpc_id = data.aws_vpc.default.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_vpc.default.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.default.ids

  tags = {
    Name = "${var.project_prefix}-s3-gateway-endpoint"
  }
}
