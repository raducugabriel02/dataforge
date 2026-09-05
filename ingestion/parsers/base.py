"""Abstract bank statement parser: shared CSV/header/error handling, one
concrete subclass per bank format (see bt.py, bcr.py, ing.py).
"""

from __future__ import annotations

import csv
import decimal
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ingestion.models import ParsedTransaction

_ROW_ERROR_TYPES = (ValueError, KeyError, decimal.InvalidOperation, ValidationError)


class SchemaDriftError(Exception):
    """Raised when a bank's CSV header no longer matches what the parser expects.

    Column order/names drifting silently would make every row in the file
    misinterpreted (e.g. debit read as credit) — so the whole file is
    rejected rather than guessing.
    """

    def __init__(self, source_bank: str, expected: Sequence[str], actual: Sequence[str]) -> None:
        super().__init__(
            f"[{source_bank}] Unexpected CSV header. "
            f"Expected {list(expected)}, got {list(actual)}. "
            "The bank likely changed its export format — update the parser before re-ingesting."
        )
        self.source_bank = source_bank
        self.expected = list(expected)
        self.actual = list(actual)


@dataclass
class RowParseError:
    line_number: int
    raw_row: dict[str, str]
    message: str


@dataclass
class ParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    errors: list[RowParseError] = field(default_factory=list)


class BankStatementParser(ABC):
    source_bank: str
    delimiter: str

    def parse(self, path: Path) -> ParseResult:
        result = ParseResult()
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            self._validate_header(reader.fieldnames)
            for line_number, row in enumerate(reader, start=2):
                try:
                    result.transactions.append(self._parse_row(row, line_number))
                except _ROW_ERROR_TYPES as exc:
                    result.errors.append(RowParseError(line_number, row, str(exc)))
        return result

    def _validate_header(self, fieldnames: Sequence[str] | None) -> None:
        expected = self._expected_header()
        if fieldnames is None or list(fieldnames) != list(expected):
            raise SchemaDriftError(self.source_bank, expected, list(fieldnames or []))

    @abstractmethod
    def _expected_header(self) -> Sequence[str]: ...

    @abstractmethod
    def _parse_row(self, row: dict[str, str], line_number: int) -> ParsedTransaction: ...
