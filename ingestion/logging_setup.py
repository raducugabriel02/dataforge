from __future__ import annotations

import sys

from loguru import logger


def configure_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, serialize=True, level="INFO")
