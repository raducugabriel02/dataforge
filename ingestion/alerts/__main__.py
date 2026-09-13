from __future__ import annotations

from ingestion.alerts import run_and_notify
from ingestion.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    print(run_and_notify())


if __name__ == "__main__":
    main()
