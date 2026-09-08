.PHONY: up down restart logs psql fake-data ingest lint format typecheck test check clean \
	dbt-deps dbt-seed dbt-snapshot dbt-run dbt-test dbt-build dbt-docs \
	airflow-up airflow-down airflow-logs airflow-restart \
	bi-up bi-down bi-logs

up:
	docker compose up -d
	@echo "Postgres starting — run 'make logs' to follow, or 'make psql' once healthy."

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f postgres

psql:
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

fake-data:
	python -m scripts.generate_fake_bank_data --bank all --months 6

ingest:
	set -a && . ./.env && set +a && python -m ingestion --bank $(BANK) $(FILE)

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy .

test:
	set -a && . ./.env && set +a && pytest -v

check: lint typecheck test

clean:
	docker compose down -v

_dbt = set -a && . ./.env && set +a && dbt

dbt-deps:
	$(_dbt) deps --project-dir dbt_project --profiles-dir dbt_project

dbt-seed:
	$(_dbt) seed --project-dir dbt_project --profiles-dir dbt_project

dbt-snapshot:
	$(_dbt) snapshot --project-dir dbt_project --profiles-dir dbt_project

dbt-run:
	$(_dbt) run --project-dir dbt_project --profiles-dir dbt_project

dbt-test:
	$(_dbt) test --project-dir dbt_project --profiles-dir dbt_project

dbt-build:
	$(_dbt) build --project-dir dbt_project --profiles-dir dbt_project

dbt-docs:
	$(_dbt) docs generate --project-dir dbt_project --profiles-dir dbt_project
	$(_dbt) docs serve --project-dir dbt_project --profiles-dir dbt_project

# Profil separat "airflow" — nepornit de `make up`, ca sa poti lucra pe Fazele 0-2
# fara cele ~4GB RAM pe care le cere Airflow. UI la http://localhost:8080
# (user/parola din AIRFLOW_ADMIN_USER/AIRFLOW_ADMIN_PASSWORD in .env).
airflow-up:
	docker compose --profile airflow up -d
	@echo "Airflow UI: http://localhost:8080 — 'make airflow-logs' pana la 'healthy'."

airflow-down:
	docker compose --profile airflow down

airflow-restart: airflow-down airflow-up

airflow-logs:
	docker compose --profile airflow logs -f airflow-webserver airflow-scheduler

# Profil separat "bi" — nepornit de `make up`. UI la http://localhost:3000.
bi-up:
	docker compose --profile bi up -d
	@echo "Metabase UI: http://localhost:3000 — primul start face setup-ul de admin."

bi-down:
	docker compose --profile bi down

bi-logs:
	docker compose --profile bi logs -f metabase
