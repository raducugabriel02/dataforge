# DataForge

Personal Data Platform & ELT Warehouse — ingest, transformare (medallion: Raw → Staging → Marts) și BI pentru date personale reale, orchestrat automat și rulabil integral local prin Docker Compose.

Detalii complete despre scop, arhitectură, stack și plan pe faze: vezi [CLAUDE.md](CLAUDE.md).

## Status

**Faza 0 — Fundația.** Doar Postgres + schemele medallion + generatorul de date fake. Fără ingestie reală încă.

## Quickstart

```bash
cp .env.example .env
make up
python -m venv .venv && source .venv/bin/activate   # sau .venv\Scripts\activate pe Windows
pip install -e ".[dev]"
make fake-data
make check   # lint + typecheck + test
```

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
