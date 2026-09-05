from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import psycopg
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingestion.config import PostgresConfig
from ingestion.models import ParsedTransaction

_INSERT_SQL = """
    INSERT INTO raw.bank_transactions
        (_row_hash, source_bank, txn_date, description, amount, balance_after, _source_file)
    VALUES
        (%(row_hash)s, %(source_bank)s, %(txn_date)s, %(description)s,
         %(amount)s, %(balance_after)s, %(source_file)s)
    ON CONFLICT (_row_hash) DO NOTHING
"""


def compute_row_hash(txn: ParsedTransaction) -> str:
    """Hash on the economic event, not the file it came from.

    Deliberately excludes _source_file: the same transactions re-exported
    under a different filename must still be recognized as duplicates.
    """
    canonical = "|".join(
        [
            txn.source_bank,
            txn.txn_date.isoformat(),
            txn.description.strip().upper(),
            f"{txn.amount:.2f}",
            f"{txn.balance_after:.2f}",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class LoadResult:
    rows_inserted: int
    rows_skipped_duplicate: int


class RawLoader:
    def __init__(self, config: PostgresConfig) -> None:
        self._config = config

    @retry(
        retry=retry_if_exception_type(psycopg.OperationalError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def load(self, transactions: list[ParsedTransaction], source_file: Path) -> LoadResult:
        inserted = 0
        with psycopg.connect(self._config.dsn) as conn, conn.cursor() as cur:
            for txn in transactions:
                cur.execute(
                    _INSERT_SQL,
                    {
                        "row_hash": compute_row_hash(txn),
                        "source_bank": txn.source_bank,
                        "txn_date": txn.txn_date,
                        "description": txn.description,
                        "amount": txn.amount,
                        "balance_after": txn.balance_after,
                        "source_file": str(source_file),
                    },
                )
                inserted += cur.rowcount
            conn.commit()

        skipped = len(transactions) - inserted
        logger.bind(
            source_file=str(source_file),
            rows_inserted=inserted,
            rows_skipped_duplicate=skipped,
        ).info("raw_load_complete")
        return LoadResult(rows_inserted=inserted, rows_skipped_duplicate=skipped)
