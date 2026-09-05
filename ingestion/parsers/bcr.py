from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ingestion.models import ParsedTransaction
from ingestion.parsers.base import BankStatementParser


class BCRParser(BankStatementParser):
    """BCR-style: semicolon-separated, single signed amount column."""

    source_bank = "bcr"
    delimiter = ";"

    def _expected_header(self) -> list[str]:
        return ["Data tranzactie", "Detalii tranzactie", "Suma", "Sold final"]

    def _parse_row(self, row: dict[str, str], line_number: int) -> ParsedTransaction:
        txn_date = datetime.strptime(row["Data tranzactie"], "%d.%m.%Y").date()
        return ParsedTransaction(
            txn_date=txn_date,
            description=row["Detalii tranzactie"],
            amount=Decimal(row["Suma"]),
            balance_after=Decimal(row["Sold final"]),
            source_bank=self.source_bank,
            source_row_number=line_number,
        )
