.PHONY: help up down restart logs ps seed test lint dbt-run dbt-test dbt-docs tf-init tf-plan tf-apply tf-destroy

help:
	@echo "Rover Mars — comandos disponibles:"
	@echo "  make up          - Levanta el stack local completo (docker compose up --build -d)"
	@echo "  make down        - Detiene y elimina los contenedores (conserva volúmenes)"
	@echo "  make restart     - down + up"
	@echo "  make logs        - Sigue los logs de todos los servicios"
	@echo "  make ps          - Estado de los servicios"
	@echo "  make seed        - Corre el simulador de forma standalone (20 soles)"
	@echo "  make test        - Corre la suite de pytest"
	@echo "  make lint        - Corre ruff sobre el código Python"
	@echo "  make dbt-run     - dbt run dentro del contenedor de Airflow"
	@echo "  make dbt-test    - dbt test dentro del contenedor de Airflow"
	@echo "  make dbt-docs    - Genera y sirve dbt docs en localhost:8081"
	@echo "  make tf-init     - terraform init en infra/aws (requiere AWS CLI configurado)"
	@echo "  make tf-plan     - terraform plan en infra/aws"
	@echo "  make tf-apply    - terraform apply en infra/aws (gasta crédito AWS — confirmar antes)"
	@echo "  make tf-destroy  - terraform destroy en infra/aws (libera recursos AWS)"

up:
	docker compose up --build -d

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

ps:
	docker compose ps

seed:
	cd simulator && pip install -r requirements.txt && \
	KAFKA_BOOTSTRAP=localhost:29092 MINIO_ENDPOINT=http://localhost:9000 \
	SIMULATION_TOTAL_SOLS=20 SIMULATION_INTERVAL_SEC=2 python mastcamz_simulator.py

test:
	pip install -r requirements-dev.txt && pytest

lint:
	pip install -r requirements-dev.txt && ruff check simulator/ ingestion/ airflow/dags/ airflow/plugins/ tests/

dbt-run:
	docker compose exec airflow_scheduler bash -c "cd /opt/airflow/dbt && dbt run --profiles-dir . --project-dir ."

dbt-test:
	docker compose exec airflow_scheduler bash -c "cd /opt/airflow/dbt && dbt test --profiles-dir . --project-dir ."

dbt-docs:
	docker compose exec airflow_scheduler bash -c "cd /opt/airflow/dbt && dbt docs generate --profiles-dir . --project-dir . && dbt docs serve --profiles-dir . --project-dir . --port 8081 --host 0.0.0.0"

tf-init:
	cd infra/aws && terraform init

tf-plan:
	cd infra/aws && terraform plan

tf-apply:
	cd infra/aws && terraform apply

tf-destroy:
	cd infra/aws && terraform destroy
