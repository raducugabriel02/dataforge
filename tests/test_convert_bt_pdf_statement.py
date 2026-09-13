from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from scripts.convert_bt_pdf_statement import (
    StatementExtractionError,
    _cluster_rows,
    _extract_from_pages,
    _Row,
    _to_decimal,
    convert,
)

# Pozitii x reprezentative pentru coloanele Debit/Credit, ca in extrasul real —
# testele nu au nevoie de "top"/"x1"/"bottom", doar de "text" si "x0" (_cluster_rows
# e testata separat mai jos; aici construim randuri deja clusterizate direct).
_DEBIT_X0 = 450.0
_CREDIT_X0 = 545.0
_HEADER_ROW = _Row(
    text="Data Descriere Debit Credit",
    words=[
        {"text": "Data", "x0": 60.0},
        {"text": "Descriere", "x0": 120.0},
        {"text": "Debit", "x0": _DEBIT_X0},
        {"text": "Credit", "x0": _CREDIT_X0},
    ],
)


def _row(*tokens: tuple[str, float]) -> _Row:
    words: list[dict[str, float | str]] = [{"text": t, "x0": x0} for t, x0 in tokens]
    return _Row(text=" ".join(t for t, _ in tokens), words=words)


def _sold_anterior(amount: str) -> _Row:
    return _row(("SOLD", 60.0), ("ANTERIOR", 100.0), (amount, _CREDIT_X0))


def _sold_final_zi(amount: str) -> _Row:
    return _row(("SOLD", 60.0), ("FINAL", 100.0), ("ZI", 140.0), (amount, _CREDIT_X0))


def _rulaj_zi(debit: str, credit: str) -> _Row:
    return _row(("RULAJ", 60.0), ("ZI", 100.0), (debit, _DEBIT_X0), (credit, _CREDIT_X0))


_STOP_ROW = _row(("RULAJ", 60.0), ("TOTAL", 100.0), ("CONT", 140.0))


def test_to_decimal_strips_thousands_separator() -> None:
    assert _to_decimal("1,037.12") == Decimal("1037.12")
    assert _to_decimal("5.00") == Decimal("5.00")


def test_cluster_rows_groups_by_y_tolerance() -> None:
    words: list[dict[str, float | str]] = [
        {"text": "A", "x0": 10.0, "top": 100.0},
        {"text": "B", "x0": 50.0, "top": 101.5},
        {"text": "C", "x0": 10.0, "top": 200.0},
    ]

    rows = _cluster_rows(words, y_tolerance=3.0)

    assert [r.text for r in rows] == ["A B", "C"]


def test_single_debit_transaction_reconstructs_balance() -> None:
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("562.54"),
            _row(
                ("02/07/2026", 60.0),
                ("Taxa", 120.0),
                ("Serviciu", 150.0),
                ("SMS", 175.0),
                ("5.00", _DEBIT_X0),
            ),
            _row(("REF:", 120.0), ("112z001261833050", 150.0)),
            _rulaj_zi("5.00", "0.00"),
            _sold_final_zi("557.54"),
            _STOP_ROW,
        ]
    ]

    transactions = _extract_from_pages(pages)

    assert len(transactions) == 1
    txn = transactions[0]
    assert txn["Data"] == "02.07.2026"
    assert txn["Descriere"] == "Taxa Serviciu SMS REF: 112z001261833050"
    assert txn["Suma Debit"] == "5.00"
    assert txn["Suma Credit"] == ""
    assert txn["Sold"] == "557.54"


def test_credit_transaction_increases_balance() -> None:
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("100.00"),
            _row(
                ("09/07/2026", 60.0), ("Incasare", 120.0), ("Instant", 160.0), ("12.00", _CREDIT_X0)
            ),
            _rulaj_zi("0.00", "12.00"),
            _sold_final_zi("112.00"),
            _STOP_ROW,
        ]
    ]

    transactions = _extract_from_pages(pages)

    assert transactions[0]["Suma Debit"] == ""
    assert transactions[0]["Suma Credit"] == "12.00"
    assert transactions[0]["Sold"] == "112.00"


def test_second_same_day_transaction_has_no_date_word_but_inherits_date() -> None:
    # Formatul real BT: data apare doar pe prima tranzactie a zilei — a doua
    # tranzactie din aceeasi zi nu mai are un cuvant de data pe randul ei.
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("500.00"),
            _row(("04/07/2026", 60.0), ("Plata", 120.0), ("POS", 150.0), ("20.00", _DEBIT_X0)),
            _row(("Comis.ridicare", 120.0), ("0.30", _DEBIT_X0)),
            _rulaj_zi("20.30", "0.00"),
            _sold_final_zi("479.70"),
            _STOP_ROW,
        ]
    ]

    transactions = _extract_from_pages(pages)

    assert len(transactions) == 2
    assert transactions[0]["Data"] == transactions[1]["Data"] == "04.07.2026"
    assert transactions[1]["Descriere"] == "Comis.ridicare"
    assert transactions[1]["Sold"] == "479.70"


def test_amount_word_position_in_row_does_not_matter() -> None:
    # Observat empiric pe extrasul real: data poate aparea DUPA suma pe rand,
    # nu doar inainte — extragerea nu trebuie sa presupuna o ordine fixa.
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("300.00"),
            _row(("Plata", 120.0), ("POS", 150.0), ("20.00", _DEBIT_X0), ("04/07/2026", 60.0)),
            _rulaj_zi("20.00", "0.00"),
            _sold_final_zi("280.00"),
            _STOP_ROW,
        ]
    ]

    transactions = _extract_from_pages(pages)

    assert transactions[0]["Data"] == "04.07.2026"
    assert transactions[0]["Suma Debit"] == "20.00"
    assert "20.00" not in transactions[0]["Descriere"]
    assert "04/07/2026" not in transactions[0]["Descriere"]


def test_inline_amount_in_description_is_not_mistaken_for_column_value() -> None:
    # "valoare tranzactie: 210.00 RON" apare des in descrieri reale — pozitia lui
    # x0 e mult la stanga fata de coloana Debit reala, deci nu trebuie confundat.
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("1000.00"),
            _row(("02/07/2026", 60.0), ("Plata", 120.0), ("VISA", 150.0), ("210.00", _DEBIT_X0)),
            _row(("valoare", 120.0), ("tranzactie:", 150.0), ("210.00", 220.0), ("RON", 260.0)),
            _rulaj_zi("210.00", "0.00"),
            _sold_final_zi("790.00"),
            _STOP_ROW,
        ]
    ]

    transactions = _extract_from_pages(pages)

    assert len(transactions) == 1
    assert transactions[0]["Suma Debit"] == "210.00"
    assert transactions[0]["Sold"] == "790.00"


def test_balance_mismatch_raises() -> None:
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("100.00"),
            _row(("02/07/2026", 60.0), ("Taxa", 120.0), ("5.00", _DEBIT_X0)),
            _rulaj_zi("5.00", "0.00"),
            _sold_final_zi("999.00"),  # gresit: ar trebui 95.00
            _STOP_ROW,
        ]
    ]

    with pytest.raises(StatementExtractionError, match="sold calculat"):
        _extract_from_pages(pages)


def test_missing_sold_anterior_raises() -> None:
    pages = [[_HEADER_ROW, _STOP_ROW]]

    with pytest.raises(StatementExtractionError, match="SOLD ANTERIOR"):
        _extract_from_pages(pages)


def test_transaction_spans_page_break_and_keeps_previous_date() -> None:
    pages = [
        [
            _HEADER_ROW,
            _sold_anterior("200.00"),
            _row(("09/07/2026", 60.0), ("Incasare", 120.0), ("12.00", _CREDIT_X0)),
        ],
        [
            _HEADER_ROW,
            _row(("Plata", 120.0), ("la", 150.0), ("POS", 170.0), ("71.00", _DEBIT_X0)),
            _rulaj_zi("71.00", "12.00"),
            _sold_final_zi("141.00"),
            _STOP_ROW,
        ],
    ]

    transactions = _extract_from_pages(pages)

    assert len(transactions) == 2
    assert transactions[1]["Data"] == "09.07.2026"
    assert transactions[1]["Sold"] == "141.00"


def test_convert_writes_expected_csv_header_and_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_transactions = [
        {
            "Data": "02.07.2026",
            "Descriere": "Taxa Serviciu SMS",
            "Suma Debit": "5.00",
            "Suma Credit": "",
            "Sold": "557.54",
        }
    ]
    monkeypatch.setattr(
        "scripts.convert_bt_pdf_statement.extract_transactions", lambda pdf_path: fake_transactions
    )
    csv_path = tmp_path / "out" / "bt.csv"

    count = convert(Path("irrelevant.pdf"), csv_path)

    assert count == 1
    content = csv_path.read_text(encoding="utf-8")
    assert content.splitlines()[0] == "Data,Descriere,Suma Debit,Suma Credit,Sold"
    assert "5.00" in content
