# ADR-013 — Amazon RDS PostgreSQL + PostGIS gestionado

resource "aws_security_group" "rds" {
  name        = "${var.project_prefix}-rds-sg"
  description = "Acceso a RDS PostgreSQL solo desde el EC2 de Airflow/Kafka"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres desde el EC2 de la app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2_app.id]
  }

  # Movido a bloque inline (2026-10-07, tras un hallazgo real de T029): un
  # aws_security_group con bloques ingress {} inline y, a la vez, una regla
  # manejada por un aws_security_group_rule separado (como estaba antes en
  # glue_job.tf) hace que Terraform compita por el control del set de
  # reglas -- cada plan intentaba BORRAR esta regla porque no estaba
  # declarada acá. Ver glue_job.tf para el security group de origen.
  ingress {
    description     = "Postgres desde la conexion JDBC de Glue"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.glue_jdbc.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "rover_mars" {
  identifier              = "${var.project_prefix}-${var.environment}"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.rds_instance_class
  allocated_storage       = 20
  storage_type            = "gp3"
  db_name                 = "rover_mars"
  username                = "rover"
  password                = var.rds_master_password
  vpc_security_group_ids  = [aws_security_group.rds.id]
  db_subnet_group_name    = aws_db_subnet_group.default.name
  publicly_accessible     = false
  skip_final_snapshot     = true
  backup_retention_period = 1     # máximo permitido en cuentas de plan gratuito (FreeTierRestrictionError)
  deletion_protection     = false # portafolio/demo: se prioriza poder destruir con terraform destroy
  # Sin esto, un cambio de password (ej. una rotación de emergencia) queda
  # en cola para la próxima ventana de mantenimiento en vez de aplicarse al
  # tiro -- agregado 2026-10-07 tras necesitar rotar la contraseña real por
  # un secreto expuesto accidentalmente en un commit (ver git log).
  apply_immediately = true

  # Nota: la extensión PostGIS se habilita post-creación con:
  #   CREATE EXTENSION IF NOT EXISTS postgis;
  # (RDS Postgres la trae disponible, pero no se activa por defecto).
}
