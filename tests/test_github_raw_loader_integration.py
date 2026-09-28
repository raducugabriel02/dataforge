"""Integration tests against a real Postgres instance for GitHubRawLoader.

Mirrors test_raw_loader_integration.py's pattern (skip if Postgres isn't
reachable, clean up before/after) but exercises GitHubRawLoader's two
distinct idempotency strategies, previously only verified live:
  * repositories/pull_requests -> upsert (mutable entity, latest state wins)
  * commits -> append-only insert-dedup (immutable entity, ON CONFLICT DO NOTHING)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from ingestion.config import PostgresConfig
from ingestion.github.models import RawCommit, RawPullRequest, RawRepository
from ingestion.loaders.github_raw_loader import GitHubRawLoader

pytestmark = pytest.mark.integration

_TEST_REPO_ID = 999_999_001
_TEST_REPO_FULL_NAME = "test-owner/test-repo"
_TEST_PR_ID = 999_999_101


def _postgres_available(config: PostgresConfig) -> bool:
    try:
        with psycopg.connect(config.dsn, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def pg_config() -> PostgresConfig:
    return PostgresConfig.from_env()


@pytest.fixture(autouse=True)
def _skip_if_no_postgres(pg_config: PostgresConfig) -> None:
    if not _postgres_available(pg_config):
        pytest.skip("Postgres not reachable — run `make up` first")


@pytest.fixture
def clean_test_rows(pg_config: PostgresConfig) -> Iterator[None]:
    def _cleanup() -> None:
        with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM raw.github_commits WHERE repo_full_name = %s",
                (_TEST_REPO_FULL_NAME,),
            )
            cur.execute("DELETE FROM raw.github_pull_requests WHERE pr_id = %s", (_TEST_PR_ID,))
            cur.execute("DELETE FROM raw.github_repositories WHERE repo_id = %s", (_TEST_REPO_ID,))
            conn.commit()

    _cleanup()
    yield
    _cleanup()


def _repository(**overrides: object) -> RawRepository:
    defaults: dict[str, object] = {
        "repo_id": _TEST_REPO_ID,
        "full_name": _TEST_REPO_FULL_NAME,
        "name": "test-repo",
        "is_private": False,
        "is_fork": False,
        "language": "Python",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "pushed_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    return RawRepository(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_loading_same_repository_three_times_upserts_not_duplicates(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = GitHubRawLoader(pg_config)
    repo = _repository()

    for _ in range(3):
        loader.load_repositories([repo])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM raw.github_repositories WHERE repo_id = %s", (_TEST_REPO_ID,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1


def test_reloading_repository_with_changed_fields_reflects_latest_state(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = GitHubRawLoader(pg_config)
    loader.load_repositories([_repository(language="Python", is_fork=False)])
    loader.load_repositories([_repository(language="TypeScript", is_fork=True)])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT language, is_fork FROM raw.github_repositories WHERE repo_id = %s",
            (_TEST_REPO_ID,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "TypeScript"
        assert row[1] is True


def test_loading_same_commit_three_times_produces_no_duplicates(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = GitHubRawLoader(pg_config)
    commit = RawCommit(
        sha="a" * 40,
        repo_full_name=_TEST_REPO_FULL_NAME,
        author_login="octocat",
        author_name="The Octocat",
        committed_at=datetime(2026, 1, 1, tzinfo=UTC),
        message="initial commit",
    )

    first = loader.load_commits([commit])
    second = loader.load_commits([commit])
    third = loader.load_commits([commit])

    assert first.rows_inserted == 1
    assert second.rows_inserted == 0
    assert third.rows_inserted == 0

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM raw.github_commits WHERE repo_full_name = %s",
            (_TEST_REPO_FULL_NAME,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1


def test_loading_same_pull_request_three_times_upserts_not_duplicates(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = GitHubRawLoader(pg_config)
    pr = RawPullRequest(
        pr_id=_TEST_PR_ID,
        number=1,
        repo_full_name=_TEST_REPO_FULL_NAME,
        state="open",
        title="Test PR",
        author_login="octocat",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=None,
        closed_at=None,
    )

    for _ in range(3):
        loader.load_pull_requests([pr])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), max(state) FROM raw.github_pull_requests WHERE pr_id = %s",
            (_TEST_PR_ID,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "open"


def test_reloading_pull_request_after_merge_reflects_latest_state(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = GitHubRawLoader(pg_config)
    opened = RawPullRequest(
        pr_id=_TEST_PR_ID,
        number=1,
        repo_full_name=_TEST_REPO_FULL_NAME,
        state="open",
        title="Test PR",
        author_login="octocat",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=None,
        closed_at=None,
    )
    merged = RawPullRequest(
        pr_id=_TEST_PR_ID,
        number=1,
        repo_full_name=_TEST_REPO_FULL_NAME,
        state="closed",
        title="Test PR",
        author_login="octocat",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=datetime(2026, 1, 3, tzinfo=UTC),
        closed_at=datetime(2026, 1, 3, tzinfo=UTC),
    )

    loader.load_pull_requests([opened])
    loader.load_pull_requests([merged])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state, merged_at IS NOT NULL FROM raw.github_pull_requests WHERE pr_id = %s",
            (_TEST_PR_ID,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "closed"
        assert row[1] is True
