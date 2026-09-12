# DataForge

Personal Data Platform & ELT Warehouse — ingest, transformare (medallion: Raw → Staging → Marts) și BI pentru date personale reale, orchestrat automat și rulabil integral local prin Docker Compose.

Detalii complete despre scop, arhitectură, stack și plan pe faze: vezi [CLAUDE.md](CLAUDE.md).

## Status

**Faza 4 — Metabase + polish v1** (completă). Postgres + ingestie idempotentă (Faza 1) + proiect dbt complet (Faza 2) + orchestrare Airflow (Faza 3) + dashboard Metabase peste `marts.*` (cheltuieli pe categorii, trend lunar, top merchants). v1 (sursa bancară) e completă.

**Faza 5 (v2) — sursa GitHub, în lucru.** Client REST paginat + retry pe rate limit, `raw.github_*`, staging + marts de productivitate (`dim_repository`, `fact_daily_productivity`), mart combinat finanțe×productivitate, DAG Airflow `github_pipeline`. Cod complet și verificat live (date sintetice + `dbt build`/`airflow tasks test`); rularea reală așteaptă un `GITHUB_TOKEN` propriu în `.env`. Rămân: polish README/interview-notes (în lucru chiar acum).

## Arhitectură

```mermaid
flowchart LR
    subgraph src["Surse"]
        csv["Extrase CSV<br/>BT / BCR / ING"]
        gh["GitHub REST API<br/>repos / commits / PR-uri"]
    end

    subgraph ingest["Ingestie Python (idempotentă)"]
        parser["BankStatementParser"]
        loader["RawLoader<br/>dedup pe _row_hash"]
        ghclient["GitHubClient<br/>paginare + retry pe rate limit"]
        ghloader["GitHubRawLoader<br/>upsert (mutabil) / dedup (imuabil)"]
    end

    subgraph dwh["Postgres — DWH (medallion)"]
        raw[("raw.bank_transactions")]
        ghraw[("raw.github_*")]
        staging[["staging views (dbt)"]]
        snapshot[("staging.expense_categories_snapshot<br/>SCD2")]
        marts[("marts.*<br/>facts + dims Kimball")]
        combined[("marts.mart_daily_finance_productivity")]
    end

    subgraph orch["Airflow — profil 'airflow'"]
        dag["bank_pipeline DAG<br/>TaskFlow API"]
        ghdag["github_pipeline DAG<br/>TaskFlow API, dynamic mapping"]
        afdb[("Postgres<br/>metadata Airflow")]
    end

    subgraph bi["Metabase — profil 'bi'"]
        dash["Dashboards"]
        mbdb[("H2<br/>app db")]
    end

    csv --> parser --> loader --> raw
    gh --> ghclient --> ghloader --> ghraw
    raw --> staging --> marts
    ghraw --> staging
    staging --> snapshot --> marts
    marts --> combined
    marts --> dash
    dag -. orchestrează .-> parser
    dag -. "dbt run/test tag:bank" .-> staging
    ghdag -. orchestrează .-> ghclient
    ghdag -. "dbt run/test tag:github,combined" .-> staging
    dag --- afdb
    ghdag --- afdb
    dash --- mbdb
```

Trei Postgres logic separate, fiecare cu un motiv concret (nu izolare "din reflex" — detalii în [Design Decisions](#design-decisions)): DWH-ul de mai sus, metadata Airflow (scheduler + webserver scriu concurent), și app DB-ul Metabase (H2 embedded, nu Postgres — un singur proces, fără concurrency reală).

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

# sursa GitHub (Faza 5, v2) — completează GITHUB_TOKEN (fine-grained PAT, read-only
# pe Contents/Metadata/Pull requests) și GITHUB_USERNAME în .env, apoi:
python -m ingestion.github
dbt build --project-dir dbt_project --profiles-dir dbt_project --select tag:github tag:combined
```

> Pe Windows cu Python 3.14, executabilele `dbt.exe`/`pip.exe` pot crăpa silențios (issue de mediu, nu de proiect) — folosește `python -m pip ...` și, pentru dbt, `python -c "from dbt.cli.main import cli; cli()" <comandă>` în loc de `dbt <comandă>` direct.

> Comenzile `make` din `Makefile` (`make up`, `make test`, etc.) fac exact pașii de mai sus. Necesită GNU Make instalat — nu vine implicit pe Windows.

### Airflow (Faza 3 + 5)

Rulează într-un **profil Docker separat** (`airflow`), nepornit de `make up` — Airflow consumă ~4GB RAM, deci rămâne opțional cât lucrezi pe dbt/ingestie:

```bash
# completează AIRFLOW_FERNET_KEY în .env (vezi comentariul din .env.example)
make airflow-up
# asteapta pana serviciile sunt "healthy"
make airflow-logs
```

UI la http://localhost:8080 (user/parolă din `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`, implicit `admin`/`admin`). Două DAG-uri, zilnice, fiecare cu propria alertă Discord la eșec (`dags/common.py`, folosit de amândouă):

- **`bank_pipeline`** — verifică `data/private/` (fallback `data/sample/`) pentru CSV-uri noi, le ingerează idempotent, apoi `dbt seed → snapshot → run → test` (tag `bank`).
- **`github_pipeline`** (Faza 5) — ingerează repos, apoi (dynamic task mapping, un task per repo) commit-uri + PR-uri, apoi `dbt run/test` pe `tag:github` + `tag:combined` (reconstruiește și mart-ul combinat finanțe×productivitate). Cere `GITHUB_TOKEN`/`GITHUB_USERNAME` completate în `.env` — altfel task-ul de ingest eșuează cu un mesaj clar, nu silențios.

Un test dbt picat oprește pipeline-ul respectiv.

```bash
make airflow-down   # oprește doar serviciile Airflow, Postgres-ul de date rămâne pornit separat
```

### Metabase (Faza 4)

La fel, profil Docker separat (`bi`), opt-in:

```bash
make bi-up
```

UI la http://localhost:3000 — primul start cere setup: creezi contul de admin local (nume/email/parolă — rămân doar în fișierul H2 din containerul tău, nu pleacă nicăieri) și conexiunea la Postgres:

| Câmp | Valoare |
|---|---|
| Host | `postgres` (numele serviciului din docker-compose, nu `localhost`) |
| Port | `5432` |
| Database name | `POSTGRES_DB` din `.env` |
| Username / Password | `POSTGRES_USER` / `POSTGRES_PASSWORD` din `.env` |
| Use a secure connection (SSL) | **nebifat** — Postgres-ul local rulează fără SSL configurat |

Dashboard-ul `Cheltuieli — Overview` (cheltuieli pe categorii, trend lunar cu medie mobilă 3 luni, top merchants) e construit direct în UI din `marts.*`, nu versionat în git — Metabase își ține definițiile în propriul app DB (H2), nu în fișiere.

```bash
make bi-down
```

## Demo

| dbt lineage graph | Dashboard Metabase |
|---|---|
| ![dbt lineage](docs/screenshots/dbt-lineage.jpg) | ![Metabase dashboard](docs/screenshots/metabase-dashboard.jpg) |

## Structură

```
infra/postgres/init/   # schema SQL rulat automat la primul start al containerului
scripts/                # utilitare, ex: generatorul de date bancare fake
ingestion/              # module Python de ingestie (bank: Faza 1, github: Faza 5)
dbt_project/            # staging + marts + seeds + snapshots (bank: Faza 2, github: Faza 5)
dags/                   # DAG-uri Airflow (bank_pipeline: Faza 3, github_pipeline: Faza 5, common.py partajat)
tests/                  # unit tests
docs/interview-notes.md # note de arhitectură construite fază cu fază
docs/screenshots/       # capturi pentru README (lineage dbt, dashboard Metabase)
```

## Date

Repo-ul public conține **doar date sintetice**. Datele financiare reale stau local, în `data/private/` (gitignored) — niciodată în git.

## Design Decisions

Versiune scurtă a deciziilor de arhitectură; explicațiile complete, construite fază cu fază, sunt în [docs/interview-notes.md](docs/interview-notes.md).

- **Scheme separate (`raw`/`staging`/`marts`) într-un singur Postgres, nu baze de date separate** — medallion e o convenție de organizare a datelor, nu un motiv de izolare la nivel de proces; un singur Postgres ține costul (RAM, conexiuni de gestionat) minim cât timp nu există concurrency reală între straturi.
- **Postgres separat pentru metadata Airflow** — scheduler-ul și webserver-ul scriu/citesc concurent, non-stop, în metadata (DAG runs, task instances); amestecat cu DWH-ul ar fi cuplat două cicluri de viață diferite (`make clean` pe unul nu trebuie să-l afecteze pe celălalt).
- **H2 embedded pentru app DB-ul Metabase, nu Postgres** — un singur proces, un singur user local, scrieri doar manuale (salvezi un dashboard) — nicio concurrency reală de rezolvat. Diferă de cazul Airflow de mai sus exact prin lipsa acestei concurențe; regula e "izolezi când există un motiv concret", nu izolare din reflex.
- **Idempotență la fiecare strat, nu doar la ingest** — dedup pe `_row_hash` în `raw`, `dbt seed`/`snapshot`/`run` toate sigure la re-rulare (detalii: [Idempotența end-to-end](docs/interview-notes.md#idempotența-end-to-end-după-faza-3)) — un DAG zilnic *va* rula de mai multe ori peste aceleași date (retry, restart), și fiecare pas trebuie să reziste la asta independent.
- **SCD Type 2 via `dbt snapshot`, nu `updated_at` simplu pe categorii** — categoriile de cheltuieli se schimbă în timp; păstrăm istoricul (`valid_from`/`valid_to`/`is_current`) ca un raport din trecut să folosească categoria validă *atunci*, nu cea curentă.
- **Airflow și Metabase în profiluri Docker opt-in (`airflow`, `bi`), nu în `make up`** — Airflow consumă ~4GB RAM; separarea permite să lucrezi pe ingestie/dbt fără costul lor, pornindu-le explicit doar când ai nevoie.
- **Idempotența la sursa GitHub aleasă per entitate, nu copiată din bank** — `raw.github_commits` e append-only cu dedup pe `(repo_full_name, sha)` ca `raw.bank_transactions`, dar `raw.github_repositories`/`raw.github_pull_requests` fac **upsert**: sunt entități mutabile (starea unui PR, `pushed_at`-ul unui repo), deci raw ține doar ultima stare cunoscută, nu un istoric. Detalii: [Extensibilitatea arhitecturii](docs/interview-notes.md#extensibilitatea-arhitecturii-pe-o-a-doua-sursă-după-faza-5).
- **`fact_daily_productivity` e sparse (doar zile cu activitate), `mart_daily_finance_productivity` e dense (fiecare zi din intervalul activ)** — un fapt Kimball ține doar evenimente reale; un mart pentru corelații are nevoie de zerouri explicite, altfel o zi fără commit-uri ar lipsi din analiză în loc să fie un punct de date real.
