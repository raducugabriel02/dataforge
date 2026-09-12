from __future__ import annotations

from loguru import logger

from ingestion.config import PostgresConfig
from ingestion.github.client import GitHubClient
from ingestion.github.config import GitHubConfig
from ingestion.github.models import RecordParseError
from ingestion.loaders.github_raw_loader import GitHubRawLoader
from ingestion.logging_setup import configure_logging


def _log_errors(errors: list[RecordParseError]) -> None:
    for error in errors:
        logger.bind(endpoint=error.endpoint, raw_record=error.raw_record).error(error.message)


def main() -> None:
    configure_logging()

    loader = GitHubRawLoader(PostgresConfig.from_env())

    with GitHubClient(GitHubConfig.from_env()) as client:
        repo_result = client.list_repositories()
        _log_errors(repo_result.errors)
        loader.load_repositories(repo_result.records)
        logger.bind(count=len(repo_result.records)).info("repositories_ingested")

        for repo in repo_result.records:
            commit_result = client.list_commits(repo.full_name)
            _log_errors(commit_result.errors)
            commit_load = loader.load_commits(commit_result.records)
            logger.bind(
                repo=repo.full_name,
                rows_inserted=commit_load.rows_inserted,
                rows_skipped_duplicate=commit_load.rows_skipped_duplicate,
            ).info("commits_ingested")

            pr_result = client.list_pull_requests(repo.full_name)
            _log_errors(pr_result.errors)
            loader.load_pull_requests(pr_result.records)
            logger.bind(repo=repo.full_name, count=len(pr_result.records)).info(
                "pull_requests_ingested"
            )


if __name__ == "__main__":
    main()
