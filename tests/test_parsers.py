from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.parsers.base import SchemaDriftError
from ingestion.parsers.bcr import BCRParser
from ingestion.parsers.bt import BTParser
from ingestion.parsers.ing import INGParser


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_bt_parser_happy_path(tmp_path: Path) -> None:
    csv_content = (
        "Data,Descriere,Suma Debit,Suma Credit,Sold\n"
        "01.03.2026,LIDL,45.32,,954.68\n"
        "02.03.2026,SALARIU,,4000.00,4954.68\n"
    )
    path = _write(tmp_path / "bt.csv", csv_content)

    result = BTParser().parse(path)

    assert result.errors == []
    assert len(result.transactions) == 2
    first = result.transactions[0]
    assert first.txn_date == date(2026, 3, 1)
    assert first.amount == Decimal("-45.32")
    assert first.balance_after == Decimal("954.68")
    assert first.source_bank == "bt"
    assert first.source_row_number == 2
    assert result.transactions[1].amount == Decimal("4000.00")
    assert result.transactions[1].source_row_number == 3


def test_bt_parser_skips_corrupt_rows_but_keeps_valid_ones(tmp_path: Path) -> None:
    csv_content = (
        "Data,Descriere,Suma Debit,Suma Credit,Sold\n"
        "01.03.2026,LIDL,45.32,,954.68\n"
        "NOT_A_DATE,COMISION NECUNOSCUT,abc,,940.00\n"
        "04.03.2026,KAUFLAND,60.00,,880.00\n"
    )
    path = _write(tmp_path / "bt_corrupt.csv", csv_content)

    result = BTParser().parse(path)

    assert len(result.transactions) == 2
    assert len(result.errors) == 1
    assert result.errors[0].line_number == 3
    assert result.errors[0].raw_row["Data"] == "NOT_A_DATE"


def test_bt_parser_rejects_row_with_both_debit_and_credit(tmp_path: Path) -> None:
    csv_content = (
        "Data,Descriere,Suma Debit,Suma Credit,Sold\n01.03.2026,AMBIGUU,10.00,10.00,1000.00\n"
    )
    path = _write(tmp_path / "bt_ambiguous.csv", csv_content)

    result = BTParser().parse(path)

    assert result.transactions == []
    assert len(result.errors) == 1


def test_bt_parser_raises_on_schema_drift(tmp_path: Path) -> None:
    csv_content = "Date,Description,Debit,Credit,Balance\n01.03.2026,LIDL,45.32,,954.68\n"
    path = _write(tmp_path / "bt_drifted.csv", csv_content)

    with pytest.raises(SchemaDriftError):
        BTParser().parse(path)


def test_bcr_parser_happy_path(tmp_path: Path) -> None:
    csv_content = (
        "Data tranzactie;Detalii tranzactie;Suma;Sold final\n01.03.2026;KAUFLAND;-120.00;2345.10\n"
    )
    path = _write(tmp_path / "bcr.csv", csv_content)

    result = BCRParser().parse(path)

    assert result.errors == []
    assert result.transactions[0].amount == Decimal("-120.00")
    assert result.transactions[0].source_bank == "bcr"


def test_ing_parser_happy_path(tmp_path: Path) -> None:
    csv_content = (
        "Booking Date,Description,Amount,Balance After Transaction\n"
        "2026-03-01,NETFLIX,-39.52,4860.48\n"
    )
    path = _write(tmp_path / "ing.csv", csv_content)

    result = INGParser().parse(path)

    assert result.errors == []
    assert result.transactions[0].txn_date == date(2026, 3, 1)
    assert result.transactions[0].source_bank == "ing"
