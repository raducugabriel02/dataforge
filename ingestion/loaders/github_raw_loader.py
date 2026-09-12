from __future__ import annotations

from dataclasses import dataclass

import psycopg
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingestion.config import PostgresConfig
from ingestion.github.models import RawCommit, RawPullRequest, RawRepository

# repo_id/pr_id are mutable-entity natural keys -> upsert keeps raw at the
# latest known state (see infra/postgres/init/03_create_github_raw_tables.sql).
_UPSERT_REPOSITORY_SQL = """
    INSERT INTO raw.github_repositories
        (repo_id, full_name, name, is_private, is_fork, language, created_at, pushed_at)
    VALUES
        (%(repo_id)s, %(full_name)s, %(name)s, %(is_private)s, %(is_fork)s,
         %(language)s, %(created_at)s, %(pushed_at)s)
    ON CONFLICT (repo_id) DO UPDATE SET
        full_name = EXCLUDED.full_name,
        name = EXCLUDED.name,
        is_private = EXCLUDED.is_private,
        is_fork = EXCLUDED.is_fork,
        language = EXCLUDED.language,
        pushed_at = EXCLUDED.pushed_at,
        _loaded_at = now()
"""

# sha is an immutable-event natural key -> plain append-only dedup.
_INSERT_COMMIT_SQL = """
    INSERT INTO raw.github_commits
        (repo_full_name, sha, author_login, author_name, committed_at, message)
    VALUES
        (%(repo_full_name)s, %(sha)s, %(author_login)s, %(author_name)s,
         %(committed_at)s, %(message)s)
    ON CONFLICT (repo_full_name, sha) DO NOTHING
"""

_UPSERT_PULL_REQUEST_SQL = """
    INSERT INTO raw.github_pull_requests
        (pr_id, number, repo_full_name, state, title, author_login,
         created_at, merged_at, closed_at)
    VALUES
        (%(pr_id)s, %(number)s, %(repo_full_name)s, %(state)s, %(title)s,
         %(author_login)s, %(created_at)s, %(merged_at)s, %(closed_at)s)
    ON CONFLICT (pr_id) DO UPDATE SET
        state = EXCLUDED.state,
        title = EXCLUDED.title,
        merged_at = EXCLUDED.merged_at,
        closed_at = EXCLUDED.closed_at,
        _loaded_at = now()
"""

_RETRY_ON_TRANSIENT_DB_ERROR = retry(
    retry=retry_if_exception_type(psycopg.OperationalError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


@dataclass
class CommitLoadResult:
    rows_inserted: int
    rows_skipped_duplicate: int


class GitHubRawLoader:
    def __init__(self, config: PostgresConfig) -> None:
        self._config = config

    @_RETRY_ON_TRANSIENT_DB_ERROR
    def load_repositories(self, repositories: list[RawRepository]) -> int:
        with psycopg.connect(self._config.dsn) as conn, conn.cursor() as cur:
            for repo in repositories:
                cur.execute(_UPSERT_REPOSITORY_SQL, repo.model_dump())
            conn.commit()
        logger.bind(rows_upserted=len(repositories)).info("github_repositories_load_complete")
        return len(repositories)

    @_RETRY_ON_TRANSIENT_DB_ERROR
    def load_commits(self, commits: list[RawCommit]) -> CommitLoadResult:
        inserted = 0
        with psycopg.connect(self._config.dsn) as conn, conn.cursor() as cur:
            for commit in commits:
                cur.execute(_INSERT_COMMIT_SQL, commit.model_dump())
                inserted += cur.rowcount
            conn.commit()
        skipped = len(commits) - inserted
        logger.bind(rows_inserted=inserted, rows_skipped_duplicate=skipped).info(
            "github_commits_load_complete"
        )
        return CommitLoadResult(rows_inserted=inserted, rows_skipped_duplicate=skipped)

    @_RETRY_ON_TRANSIENT_DB_ERROR
    def load_pull_requests(self, pull_requests: list[RawPullRequest]) -> int:
        with psycopg.connect(self._config.dsn) as conn, conn.cursor() as cur:
            for pr in pull_requests:
                cur.execute(_UPSERT_PULL_REQUEST_SQL, pr.model_dump())
            conn.commit()
        logger.bind(rows_upserted=len(pull_requests)).info("github_pull_requests_load_complete")
        return len(pull_requests)
