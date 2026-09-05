"""Integration test against a real Postgres instance.

Skips itself (rather than failing) if Postgres isn't reachable — run
`make up` first. Kept separate from the pure-unit parser tests because it
exercises the actual idempotency guarantee end-to-end: same rows loaded
three times must land exactly once in raw.bank_transactions.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from ingestion.config import PostgresConfig
from ingestion.loaders.raw_loader import RawLoader
from ingestion.models import ParsedTransaction

pytestmark = pytest.mark.integration

_TEST_SOURCE_BANK = "test_bank"


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
                "DELETE FROM raw.bank_transactions WHERE source_bank = %s", (_TEST_SOURCE_BANK,)
            )
            conn.commit()

    _cleanup()
    yield
    _cleanup()


def test_loading_same_file_three_times_produces_no_duplicates(
    pg_config: PostgresConfig, clean_test_rows: None
) -> None:
    transactions = [
        ParsedTransaction(
            txn_date=date(2026, 1, 1),
            description="TEST MERCHANT",
            amount=Decimal("-10.00"),
            balance_after=Decimal("990.00"),
            source_bank=_TEST_SOURCE_BANK,
        ),
        ParsedTransaction(
            txn_date=date(2026, 1, 2),
            description="TEST MERCHANT",
            amount=Decimal("-20.00"),
            balance_after=Decimal("970.00"),
            source_bank=_TEST_SOURCE_BANK,
        ),
    ]
    loader = RawLoader(pg_config)
    source_file = Path("fixture.csv")

    first = loader.load(transactions, source_file)
    second = loader.load(transactions, source_file)
    third = loader.load(transactions, source_file)

    assert first.rows_inserted == 2
    assert second.rows_inserted == 0
    assert third.rows_inserted == 0

    with psycopg.connect(pg_config.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM raw.bank_transactions WHERE source_bank = %s",
            (_TEST_SOURCE_BANK,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 2
