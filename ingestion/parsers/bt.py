from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ingestion.models import ParsedTransaction
from ingestion.parsers.base import BankStatementParser


class BTParser(BankStatementParser):
    """BT-style: comma-separated, separate debit/credit columns."""

    source_bank = "bt"
    delimiter = ","

    def _expected_header(self) -> list[str]:
        return ["Data", "Descriere", "Suma Debit", "Suma Credit", "Sold"]

    def _parse_row(self, row: dict[str, str]) -> ParsedTransaction:
        txn_date = datetime.strptime(row["Data"], "%d.%m.%Y").date()
        debit = row["Suma Debit"].strip()
        credit = row["Suma Credit"].strip()
        if debit and credit:
            raise ValueError(f"row has both debit and credit values: {row}")
        if debit:
            amount = -Decimal(debit)
        elif credit:
            amount = Decimal(credit)
        else:
            raise ValueError(f"row has neither debit nor credit value: {row}")
        return ParsedTransaction(
            txn_date=txn_date,
            description=row["Descriere"],
            amount=amount,
            balance_after=Decimal(row["Sold"]),
            source_bank=self.source_bank,
        )
