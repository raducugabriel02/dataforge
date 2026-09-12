"""Pipeline zilnic pentru sursa GitHub (Faza 5).

Flux: ingest repos (raw.github_repositories) -> pentru fiecare repo, in paralel
(dynamic task mapping, acelasi pattern ca bank_pipeline.check_source/ingest),
ingest commits + pull requests -> transformari dbt filtrate pe tag-urile
"github" si "combined" (reconstruieste si mart_daily_finance_productivity,
vezi common.dbt_command). Mai simplu decat bank_pipeline: nicio sursa nu
are seed-uri sau snapshot SCD2 aici, deci DAG-ul nu copiaza acea secventa
degeaba — orchestreaza doar subcomenzile dbt de care sursa asta chiar are
nevoie.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from common import dbt_command, notify_discord_failure


@dag(
    dag_id="github_pipeline",
    description=(
        "Ingest GitHub (repos, commits, PR-uri) + transformari dbt (staging -> marts), zilnic."
    ),
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Europe/Bucharest"),
    catchup=False,
    tags=["github", "productivity"],
    default_args={"on_failure_callback": notify_discord_failure, "retries": 0},
)
def github_pipeline() -> None:
    @task
    def ingest_repositories() -> list[str]:
        """Ingesteaza raw.github_repositories si intoarce full_name-urile
        ingerate, ca sa fie mapate dinamic pe task-ul de mai jos.
        """
        from ingestion.config import PostgresConfig
        from ingestion.github.client import GitHubClient
        from ingestion.github.config import GitHubConfig
        from ingestion.loaders.github_raw_loader import GitHubRawLoader
        from ingestion.logging_setup import configure_logging

        configure_logging()

        with GitHubClient(GitHubConfig.from_env()) as client:
            result = client.list_repositories()

        for error in result.errors:
            print(f"[repos] {error.message}")

        loader = GitHubRawLoader(PostgresConfig.from_env())
        loader.load_repositories(result.records)

        return [repo.full_name for repo in result.records]

    @task
    def ingest_commits_and_pull_requests(repo_full_name: str) -> str:
        from ingestion.config import PostgresConfig
        from ingestion.github.client import GitHubClient
        from ingestion.github.config import GitHubConfig
        from ingestion.loaders.github_raw_loader import GitHubRawLoader
        from ingestion.logging_setup import configure_logging

        configure_logging()
        loader = GitHubRawLoader(PostgresConfig.from_env())

        with GitHubClient(GitHubConfig.from_env()) as client:
            commit_result = client.list_commits(repo_full_name)
            for error in commit_result.errors:
                print(f"[commits/{repo_full_name}] {error.message}")
            commit_load = loader.load_commits(commit_result.records)

            pr_result = client.list_pull_requests(repo_full_name)
            for error in pr_result.errors:
                print(f"[pulls/{repo_full_name}] {error.message}")
            pr_count = loader.load_pull_requests(pr_result.records)

        return (
            f"{repo_full_name} — {commit_load.rows_inserted} commit-uri noi "
            f"({commit_load.rows_skipped_duplicate} deja existente), {pr_count} PR-uri"
        )

    @task.bash
    def dbt_run() -> str:
        return dbt_command("run", "github", "combined")

    @task.bash
    def dbt_test() -> str:
        return dbt_command("test", "github", "combined")

    repos = ingest_repositories()
    ingested = ingest_commits_and_pull_requests.expand(repo_full_name=repos)

    ingested >> dbt_run() >> dbt_test()


github_pipeline()
