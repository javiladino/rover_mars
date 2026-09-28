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
