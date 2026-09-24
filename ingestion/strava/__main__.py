from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from ingestion.config import PostgresConfig
from ingestion.loaders.strava_raw_loader import StravaRawLoader
from ingestion.logging_setup import configure_logging
from ingestion.strava.parser import StravaActivityParser


def main() -> None:
    configure_logging()

    arg_parser = argparse.ArgumentParser(
        description=(
            "Parse Strava's bulk-export activities.csv and load it into raw.strava_activities"
        ),
    )
    arg_parser.add_argument("path", type=Path)
    args = arg_parser.parse_args()

    result = StravaActivityParser().parse(args.path)

    for error in result.errors:
        logger.bind(line_number=error.line_number, raw_row=error.raw_row).error(error.message)

    logger.bind(
        valid_rows=len(result.activities),
        error_rows=len(result.errors),
    ).info("parse_complete")

    if not result.activities:
        logger.warning("no_valid_activities_to_load")
        return

    loader = StravaRawLoader(PostgresConfig.from_env())
    loader.load(result.activities)


if __name__ == "__main__":
    main()
