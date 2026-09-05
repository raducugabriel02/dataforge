.PHONY: up down restart logs psql fake-data test lint format typecheck check clean

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
