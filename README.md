# DataForge

Personal Data Platform & ELT Warehouse — ingest, transformare (medallion: Raw → Staging → Marts) și BI pentru date personale reale, orchestrat automat și rulabil integral local prin Docker Compose.

Detalii complete despre scop, arhitectură, stack și plan pe faze: vezi [CLAUDE.md](CLAUDE.md).

## Status

**Faza 1 — Ingestia CSV bancar.** Postgres + schemele medallion + parsere per bancă (BT/BCR/ING) + loader idempotent în `raw.bank_transactions`.

## Quickstart

```bash
cp .env.example .env
# dacă ai deja alt Postgres pe portul 5432 (local sau alt proiect Docker),
# schimbă POSTGRES_PORT din .env înainte de a porni containerul
docker compose up -d

python -m venv .venv && source .venv/bin/activate   # sau .venv\Scripts\activate pe Windows
pip install -e ".[dev]"

python -m scripts.generate_fake_bank_data --bank all --months 6

# rulează testele cu variabilele din .env încărcate în mediu
set -a && . ./.env && set +a
pytest -v
ruff check . && mypy .

# ingest efectiv al unui extras (idempotent — poți rula de mai multe ori)
python -m ingestion --bank bt data/sample/bt_statement.csv
```

> Comenzile `make` din `Makefile` (`make up`, `make test`, etc.) fac exact pașii de mai sus. Necesită GNU Make instalat — nu vine implicit pe Windows.

## Structură

```
infra/postgres/init/   # schema SQL rulat automat la primul start al containerului
scripts/                # utilitare, ex: generatorul de date bancare fake
ingestion/              # module Python de ingestie (Faza 1+)
dbt_project/            # proiect dbt (creat în Faza 2)
dags/                   # DAG-uri Airflow (Faza 3+)
tests/                  # unit tests
docs/interview-notes.md # note de arhitectură construite fază cu fază
```

## Date

Repo-ul public conține **doar date sintetice**. Datele financiare reale stau local, în `data/private/` (gitignored) — niciodată în git.
