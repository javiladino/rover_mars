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
  backup_retention_period = 3
  deletion_protection     = false # portafolio/demo: se prioriza poder destruir con terraform destroy

  # Nota: la extensión PostGIS se habilita post-creación con:
  #   CREATE EXTENSION IF NOT EXISTS postgis;
  # (RDS Postgres la trae disponible, pero no se activa por defecto).
}
