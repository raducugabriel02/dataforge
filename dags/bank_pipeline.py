"""Pipeline zilnic pentru extrasele bancare.

Flux: verifica sursele CSV disponibile -> ingest idempotent in raw.bank_transactions
-> transformari dbt (seed -> snapshot SCD2 -> run -> test, filtrate pe tag "bank").
Un test dbt picat opreste pipeline-ul (task-urile ulterioare nu mai ruleaza) si
trimite o alerta pe Discord.
"""

from __future__ import annotations

import os
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from common import dbt_command, notify_discord_failure

DATA_DIR = Path(os.environ.get("DATAFORGE_DATA_DIR", "/opt/dataforge/data/private"))
DATA_DIR_FALLBACK = Path(
    os.environ.get("DATAFORGE_DATA_DIR_FALLBACK", "/opt/dataforge/data/sample")
)
BANKS = ["bt", "bcr", "ing"]


@dag(
    dag_id="bank_pipeline",
    description="Ingest extrase bancare + transformari dbt (staging -> marts), zilnic.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Bucharest"),
    catchup=False,
    # dbt run/test nu sunt safe la executie concurenta pe acelasi schema Postgres
    # (folosesc pattern-ul create+rename -> "__dbt_backup", care nu e process-safe) —
    # fortam runurile sa se execute strict secvential, altfel doua DagRun-uri simultane
    # (ex. dupa un catchup cu Docker oprit cateva zile) se pot ciocni pe aceeasi relatie.
    max_active_runs=1,
    tags=["bank", "finance"],
    default_args={"on_failure_callback": notify_discord_failure, "retries": 0},
)
def bank_pipeline() -> None:
    @task
    def check_source() -> list[dict[str, str]]:
        """Cauta extrase CSV noi in data/private (date reale) si, daca nu exista
        niciunul acolo, cade pe data/sample (demo). Nu tine evidenta explicita a
        fisierelor deja ingerate — idempotenta e responsabilitatea RawLoader-ului
        (dedup pe _row_hash), asa ca re-ingerarea acelorasi fisiere e sigura.
        """
        source_dir = DATA_DIR if any(DATA_DIR.glob("*.csv")) else DATA_DIR_FALLBACK
        print(f"Caut extrase bancare in {source_dir}")

        found: list[dict[str, str]] = [
            {"bank": bank, "path": str(csv_path)}
            for bank in BANKS
            for csv_path in sorted(source_dir.glob(f"{bank}*.csv"))
        ]

        if not found:
            print("Niciun CSV gasit — dbt tot ruleaza, pe datele deja ingerate anterior")
        return found

    @task
    def ingest(source: dict[str, str]) -> str:
        from ingestion.config import PostgresConfig
        from ingestion.loaders.raw_loader import RawLoader
        from ingestion.logging_setup import configure_logging
        from ingestion.parsers.bcr import BCRParser
        from ingestion.parsers.bt import BTParser
        from ingestion.parsers.ing import INGParser

        configure_logging()
        parsers = {"bt": BTParser, "bcr": BCRParser, "ing": INGParser}

        path = Path(source["path"])
        parser = parsers[source["bank"]]()
        # SchemaDriftError se propaga aici si pica task-ul — corect: un CSV cu
        # headerul schimbat nu trebuie ingerat silentios.
        result = parser.parse(path)

        for error in result.errors:
            print(f"[{source['bank']}] linia {error.line_number}: {error.message}")

        if not result.transactions:
            return f"{source['bank']}:{path.name} — 0 randuri valide ({len(result.errors)} erori)"

        loader = RawLoader(PostgresConfig.from_env())
        loader.load(result.transactions, path)
        return (
            f"{source['bank']}:{path.name} — {len(result.transactions)} randuri incarcate "
            f"({len(result.errors)} erori)"
        )

    @task.bash
    def dbt_seed() -> str:
        return dbt_command("seed", "bank")

    @task.bash
    def dbt_snapshot() -> str:
        return dbt_command("snapshot", "bank")

    @task.bash
    def dbt_run() -> str:
        return dbt_command("run", "bank")

    @task.bash
    def dbt_test() -> str:
        return dbt_command("test", "bank")

    @task
    def check_alerts() -> str:
        """Ruleaza dupa ce dbt_test a trecut — alertele financiare (buget,
        sold, tranzactie mare) sunt un extra peste un pipeline deja sanatos,
        nu o precondifie a lui. Best-effort: o eroare la trimiterea emailului
        nu pica task-ul (vezi EmailSender), doar o eroare de query Postgres ar.
        """
        from ingestion.alerts import run_and_notify
        from ingestion.logging_setup import configure_logging

        configure_logging()
        return run_and_notify()

    sources = check_source()
    # dynamic task mapping: cate un task `ingest` per fisier gasit, in paralel,
    # in loc de un task fix per banca — se adapteaza automat la cate fisiere exista.
    ingested = ingest.expand(source=sources)

    ingested >> dbt_seed() >> dbt_snapshot() >> dbt_run() >> dbt_test() >> check_alerts()


bank_pipeline()
