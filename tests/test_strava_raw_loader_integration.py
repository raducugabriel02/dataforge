"""Integration tests against a real Postgres instance for StravaRawLoader.

Mirrors test_raw_loader_integration.py's pattern (skip if Postgres isn't
reachable, clean up before/after) — StravaRawLoader's upsert-on-activity_id
strategy (mutable entity: a user can rename/retype an activity between
exports) was previously only verified live, never in an automated test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from ingestion.config import PostgresConfig
from ingestion.loaders.strava_raw_loader import StravaRawLoader
from ingestion.strava.models import RawActivity

pytestmark = pytest.mark.integration

_TEST_ACTIVITY_ID = 999_999_201


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
                "DELETE FROM raw.strava_activities WHERE activity_id = %s", (_TEST_ACTIVITY_ID,)
            )
            conn.commit()

    _cleanup()
    yield
    _cleanup()


def _activity(**overrides: object) -> RawActivity:
    defaults: dict[str, object] = {
        "activity_id": _TEST_ACTIVITY_ID,
        "activity_date": datetime(2026, 1, 1, tzinfo=UTC),
        "name": "Morning Run",
        "activity_type": "Run",
        "elapsed_time_seconds": 1800,
        "distance_meters": Decimal("5000"),
        "moving_time_seconds": 1750,
        "average_heart_rate": Decimal("145"),
        "max_heart_rate": Decimal("172"),
        "calories": Decimal("420"),
    }
    return RawActivity(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_loading_same_activity_three_times_upserts_not_duplicates(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = StravaRawLoader(pg_config)
    activity = _activity()

    for _ in range(3):
        loader.load([activity])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM raw.strava_activities WHERE activity_id = %s",
            (_TEST_ACTIVITY_ID,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1


def test_reloading_activity_with_renamed_and_retyped_fields_reflects_latest_state(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    loader = StravaRawLoader(pg_config)
    loader.load([_activity(name="Morning Run", activity_type="Run")])
    loader.load([_activity(name="Easy Recovery Jog", activity_type="Walk")])

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name, activity_type FROM raw.strava_activities WHERE activity_id = %s",
            (_TEST_ACTIVITY_ID,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Easy Recovery Jog"
        assert row[1] == "Walk"
