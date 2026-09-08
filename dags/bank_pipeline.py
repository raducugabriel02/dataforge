"""Pipeline zilnic pentru extrasele bancare.

Flux: verifica sursele CSV disponibile -> ingest idempotent in raw.bank_transactions
-> transformari dbt (seed -> snapshot SCD2 -> run -> test, filtrate pe tag "bank").
Un test dbt picat opreste pipeline-ul (task-urile ulterioare nu mai ruleaza) si
trimite o alerta pe Discord.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

import pendulum
from airflow.decorators import dag, task

DATA_DIR = Path(os.environ.get("DATAFORGE_DATA_DIR", "/opt/dataforge/data/private"))
DATA_DIR_FALLBACK = Path(
    os.environ.get("DATAFORGE_DATA_DIR_FALLBACK", "/opt/dataforge/data/sample")
)
DBT_PROJECT_DIR = os.environ.get("DBT_PROJECT_DIR", "/opt/dataforge/dbt_project")
BANKS = ["bt", "bcr", "ing"]

DBT_BASE_CMD = (
    f"dbt {{subcommand}} --select tag:bank "
    f"--project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROJECT_DIR}"
)


def notify_discord_failure(context: dict[str, Any]) -> None:
    """default_args on_failure_callback: trimite o alerta pe Discord daca orice
    task din DAG esueaza. Best-effort — o eroare la trimitere nu trebuie sa
    ascunda eroarea reala a pipeline-ului, deci doar loghez, nu ridic exceptie.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL nesetat — sar peste notificare")
        return

    task_instance = context["task_instance"]
    payload = {
        "content": (
            f"🔴 **{context['dag'].dag_id}** a esuat pe task `{task_instance.task_id}` "
            f"(run `{context['run_id']}`)\n{task_instance.log_url}"
        )
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except Exception as exc:  # pragma: no cover - notificare best-effort
        print(f"Trimiterea notificarii Discord a esuat: {exc}")


@dag(
    dag_id="bank_pipeline",
    description="Ingest extrase bancare + transformari dbt (staging -> marts), zilnic.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Bucharest"),
    catchup=False,
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
        return DBT_BASE_CMD.format(subcommand="seed")

    @task.bash
    def dbt_snapshot() -> str:
        return DBT_BASE_CMD.format(subcommand="snapshot")

    @task.bash
    def dbt_run() -> str:
        return DBT_BASE_CMD.format(subcommand="run")

    @task.bash
    def dbt_test() -> str:
        return DBT_BASE_CMD.format(subcommand="test")

    sources = check_source()
    # dynamic task mapping: cate un task `ingest` per fisier gasit, in paralel,
    # in loc de un task fix per banca — se adapteaza automat la cate fisiere exista.
    ingested = ingest.expand(source=sources)

    ingested >> dbt_seed() >> dbt_snapshot() >> dbt_run() >> dbt_test()


bank_pipeline()
