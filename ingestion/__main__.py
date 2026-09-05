from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from ingestion.config import PostgresConfig
from ingestion.loaders.raw_loader import RawLoader
from ingestion.logging_setup import configure_logging
from ingestion.parsers.base import BankStatementParser
from ingestion.parsers.bcr import BCRParser
from ingestion.parsers.bt import BTParser
from ingestion.parsers.ing import INGParser

PARSERS: dict[str, type[BankStatementParser]] = {
    "bt": BTParser,
    "bcr": BCRParser,
    "ing": INGParser,
}


def main() -> None:
    configure_logging()

    arg_parser = argparse.ArgumentParser(
        description="Parse a bank statement CSV and load it into raw.bank_transactions"
    )
    arg_parser.add_argument("--bank", choices=list(PARSERS), required=True)
    arg_parser.add_argument("path", type=Path)
    args = arg_parser.parse_args()

    bank_parser = PARSERS[args.bank]()
    result = bank_parser.parse(args.path)

    for error in result.errors:
        logger.bind(
            source_bank=args.bank,
            line_number=error.line_number,
            raw_row=error.raw_row,
        ).error(error.message)

    logger.bind(
        source_bank=args.bank,
        valid_rows=len(result.transactions),
        error_rows=len(result.errors),
    ).info("parse_complete")

    if not result.transactions:
        logger.warning("no_valid_transactions_to_load")
        return

    loader = RawLoader(PostgresConfig.from_env())
    loader.load(result.transactions, args.path)


if __name__ == "__main__":
    main()
