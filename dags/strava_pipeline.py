"""Pipeline zilnic pentru sursa Strava (Faza 6, v3).

Spre deosebire de github_pipeline (poll live pe API), sursa Strava e un
export manual, dropped periodic in data/private/strava_export_raw/activities.csv
(Strava limiteaza exportul la o cerere/saptamana - vezi docs/interview-notes.md).
Flux: cauta fisierul -> ingest idempotent (upsert pe activity_id, ca la
github repos/PRs) -> transformari dbt filtrate pe tag-urile "strava" si
"combined" (reconstruieste si mart-ul combinat finante x productivitate x
fitness). Un test dbt picat opreste pipeline-ul.
"""

from __future__ import annotations

import os
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from common import dbt_command, notify_discord_failure

DATA_DIR = Path(os.environ.get("DATAFORGE_DATA_DIR", "/opt/dataforge/data/private"))
ACTIVITIES_CSV = DATA_DIR / "strava_export_raw" / "activities.csv"


@dag(
    dag_id="strava_pipeline",
    description="Ingest export Strava (activities.csv) + transformari dbt (staging -> marts).",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Bucharest"),
    catchup=False,
    # vezi bank_pipeline.py: dbt run/test nu e safe la executie concurenta pe
    # acelasi schema Postgres, deci fortam runurile acestui DAG sa fie secventiale.
    max_active_runs=1,
    tags=["strava", "fitness"],
    default_args={"on_failure_callback": notify_discord_failure, "retries": 0},
)
def strava_pipeline() -> None:
    @task
    def check_source() -> str | None:
        """Cauta activities.csv din ultimul export Strava. Spre deosebire de
        bank_pipeline (fisiere multiple, glob pe banca), aici e un singur
        fisier fix, mereu suprascris de fiecare export nou — nu exista
        fallback pe date sintetice, sursa asta ramane goala pana la primul
        export real (vezi README, sectiunea Date).
        """
        if not ACTIVITIES_CSV.exists():
            print(f"Niciun export Strava la {ACTIVITIES_CSV} — dbt ruleaza pe datele deja ingerate")
            return None
        return str(ACTIVITIES_CSV)

    @task
    def ingest(path: str | None) -> str:
        if path is None:
            return "niciun export Strava de ingerat"

        from ingestion.config import PostgresConfig
        from ingestion.loaders.strava_raw_loader import StravaRawLoader
        from ingestion.logging_setup import configure_logging
        from ingestion.strava.parser import StravaActivityParser

        configure_logging()

        result = StravaActivityParser().parse(Path(path))
        for error in result.errors:
            print(f"[strava] linia {error.line_number}: {error.message}")

        if not result.activities:
            return f"activities.csv — 0 randuri valide ({len(result.errors)} erori)"

        loader = StravaRawLoader(PostgresConfig.from_env())
        loader.load(result.activities)
        return (
            f"activities.csv — {len(result.activities)} activitati incarcate "
            f"({len(result.errors)} erori)"
        )

    @task.bash
    def dbt_run() -> str:
        return dbt_command("run", "strava", "combined")

    @task.bash
    def dbt_test() -> str:
        return dbt_command("test", "strava", "combined")

    ingested = ingest(check_source())

    ingested >> dbt_run() >> dbt_test()


strava_pipeline()
