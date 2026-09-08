# DataForge

Personal Data Platform & ELT Warehouse — ingest, transformare (medallion: Raw → Staging → Marts) și BI pentru date personale reale, orchestrat automat și rulabil integral local prin Docker Compose.

Detalii complete despre scop, arhitectură, stack și plan pe faze: vezi [CLAUDE.md](CLAUDE.md).

## Status

**Faza 3 — Orchestrare Airflow.** Postgres + ingestie idempotentă (Faza 1) + proiect dbt complet (Faza 2) + DAG `bank_pipeline` (TaskFlow API): verificare sursă → ingest → `dbt seed`/`snapshot`/`run`/`test` → alertă Discord la eșec. Airflow rulează într-un profil Docker separat, cu Postgres propriu pentru metadata (izolat de DWH).

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
python -m ingestion --bank bcr data/sample/bcr_statement.csv
python -m ingestion --bank ing data/sample/ing_statement.csv

# instalează dbt (grup separat de dependențe, ține pinurile departe de restul proiectului)
pip install -e ".[dbt]"

# transformare: seed -> snapshot (SCD2) -> run -> test, sau toate deodată cu build
dbt deps --project-dir dbt_project --profiles-dir dbt_project
dbt build --project-dir dbt_project --profiles-dir dbt_project

# lineage + documentație interactivă
dbt docs generate --project-dir dbt_project --profiles-dir dbt_project
dbt docs serve --project-dir dbt_project --profiles-dir dbt_project
```

> Comenzile `make` din `Makefile` (`make up`, `make test`, etc.) fac exact pașii de mai sus. Necesită GNU Make instalat — nu vine implicit pe Windows.

### Airflow (Faza 3)

Rulează într-un **profil Docker separat** (`airflow`), nepornit de `make up` — Airflow consumă ~4GB RAM, deci rămâne opțional cât lucrezi pe dbt/ingestie:

```bash
# completează AIRFLOW_FERNET_KEY în .env (vezi comentariul din .env.example)
make airflow-up
# asteapta pana serviciile sunt "healthy"
make airflow-logs
```

UI la http://localhost:8080 (user/parolă din `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`, implicit `admin`/`admin`). DAG-ul `bank_pipeline` rulează zilnic: verifică `data/private/` (fallback `data/sample/`) pentru CSV-uri noi, le ingerează idempotent, apoi `dbt seed → snapshot → run → test` (filtrate pe tag `bank`). Un test picat oprește pipeline-ul și — dacă `DISCORD_WEBHOOK_URL` e setat în `.env` — trimite o alertă pe Discord.

```bash
make airflow-down   # oprește doar serviciile Airflow, Postgres-ul de date rămâne pornit separat
```

## Structură

```
infra/postgres/init/   # schema SQL rulat automat la primul start al containerului
scripts/                # utilitare, ex: generatorul de date bancare fake
ingestion/              # module Python de ingestie (Faza 1+)
dbt_project/            # staging + marts + seeds + snapshots (Faza 2)
dags/                   # DAG-uri Airflow (Faza 3+)
tests/                  # unit tests
docs/interview-notes.md # note de arhitectură construite fază cu fază
```

## Date

Repo-ul public conține **doar date sintetice**. Datele financiare reale stau local, în `data/private/` (gitignored) — niciodată în git.
