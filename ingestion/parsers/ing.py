from __future__ import annotations

from datetime import date
from decimal import Decimal

from ingestion.models import ParsedTransaction
from ingestion.parsers.base import BankStatementParser


class INGParser(BankStatementParser):
    """ING-style: comma-separated, ISO dates, English column names."""

    source_bank = "ing"
    delimiter = ","

    def _expected_header(self) -> list[str]:
        return ["Booking Date", "Description", "Amount", "Balance After Transaction"]

    def _parse_row(self, row: dict[str, str], line_number: int) -> ParsedTransaction:
        return ParsedTransaction(
            txn_date=date.fromisoformat(row["Booking Date"]),
            description=row["Description"],
            amount=Decimal(row["Amount"]),
            balance_after=Decimal(row["Balance After Transaction"]),
            source_bank=self.source_bank,
            source_row_number=line_number,
        )
