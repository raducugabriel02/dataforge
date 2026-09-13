"""Converteste un extras de cont BT in format PDF in CSV-ul asteptat de
BTParser (Data,Descriere,Suma Debit,Suma Credit,Sold).

De ce exista scriptul asta: BT24 nu ofera intotdeauna export CSV/Excel, doar
PDF. Spre deosebire de un CSV, extrasul PDF nu are o coloana de sold dupa
fiecare tranzactie — doar solduri zilnice ("SOLD FINAL ZI") si totaluri
zilnice ("RULAJ ZI"). Soldul per-tranzactie e reconstruit pornind de la
"SOLD ANTERIOR" si cumuland sumele semnate, in ordinea in care apar in PDF —
si validat la fiecare zi contra "SOLD FINAL ZI" raportat de banca: daca nu
coincid, extragerea e gresita undeva si scriptul opreste cu eroare in loc sa
scrie date financiare gresite in CSV (acelasi fail-fast ca la parserele CSV).

Coloanele Debit/Credit sunt identificate dupa pozitia x a header-ului, nu
prin regex pe text liniarizat — mai robust la sume care apar inline in
descrieri (ex: "valoare tranzactie: 210.00 RON"), care sunt pozitionate mult
mai la stanga decat coloanele reale.

Usage: python -m scripts.convert_bt_pdf_statement <input.pdf> <output.csv>
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

_AMOUNT_RE = re.compile(r"^\d+(?:,\d{3})*\.\d{2}$")
_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\b")
_AMOUNT_X_TOLERANCE = 40.0


class StatementExtractionError(Exception):
    """Solduri calculate din tranzactii nu se potrivesc cu cele raportate de banca."""


@dataclass
class _Row:
    text: str
    words: list[dict[str, float | str]]


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def _cluster_rows(words: list[dict[str, float | str]], y_tolerance: float = 3.0) -> list[_Row]:
    rows: list[list[dict[str, float | str]]] = []
    current: list[dict[str, float | str]] = []
    current_top: float | None = None
    for word in sorted(words, key=lambda w: (round(float(w["top"])), float(w["x0"]))):
        top = float(word["top"])
        if current_top is None or abs(top - current_top) <= y_tolerance:
            current.append(word)
            current_top = top if current_top is None else current_top
        else:
            rows.append(current)
            current = [word]
            current_top = top
    if current:
        rows.append(current)
    return [_Row(text=" ".join(str(w["text"]) for w in row), words=row) for row in rows]


@dataclass
class _PendingTxn:
    date: str
    base_desc: str
    amount_word: str
    amount_side: str


def _extract_from_pages(pages: list[list[_Row]]) -> list[dict[str, str]]:
    """Motorul de extragere, separat de I/O-ul pdfplumber — primeste randuri deja
    clusterizate (o lista de pagini, fiecare o lista de _Row) ca sa poata fi testat
    cu randuri construite manual, fara sa aiba nevoie de un fisier PDF real.
    """
    rows_out: list[dict[str, str]] = []
    debit_x0: float | None = None
    credit_x0: float | None = None
    opening_balance: Decimal | None = None
    running_balance: Decimal | None = None
    current_date: str | None = None
    pending_txn: _PendingTxn | None = None
    pending_continuation: list[str] = []
    stopped = False

    def flush() -> None:
        nonlocal pending_txn, pending_continuation, running_balance
        if pending_txn is None:
            return
        description = " ".join(
            p for p in [pending_txn.base_desc, *pending_continuation] if p
        ).strip()
        assert running_balance is not None
        amount = _to_decimal(pending_txn.amount_word)
        if pending_txn.amount_side == "debit":
            running_balance -= amount
            debit_str, credit_str = pending_txn.amount_word, ""
        else:
            running_balance += amount
            debit_str, credit_str = "", pending_txn.amount_word
        rows_out.append(
            {
                "Data": pending_txn.date,
                "Descriere": description,
                "Suma Debit": debit_str,
                "Suma Credit": credit_str,
                "Sold": str(running_balance),
            }
        )
        pending_txn = None
        pending_continuation = []

    for rows in pages:
        header_seen = False
        for row in rows:
            if debit_x0 is None:
                for w in row.words:
                    if w["text"] == "Debit":
                        debit_x0 = float(w["x0"])
                    elif w["text"] == "Credit":
                        credit_x0 = float(w["x0"])

            if not header_seen:
                if "Descriere" in row.text and "Debit" in row.text and "Credit" in row.text:
                    header_seen = True
                continue

            if "RULAJ TOTAL CONT" in row.text:
                stopped = True
                break

            # Ordinea cuvintelor pe rand nu urmareste mereu x0 crescator (observat
            # empiric: data sau eticheta pot aparea dupa suma). Cautam valorile
            # oriunde in rand / in lista de cuvinte, nu presupunem o ordine fixa.
            if "SOLD ANTERIOR" in row.text:
                flush()
                m = re.search(r"(\d+(?:,\d{3})*\.\d{2})", row.text)
                if not m:
                    raise StatementExtractionError(f"nu pot citi SOLD ANTERIOR: {row.text!r}")
                opening_balance = _to_decimal(m.group(1))
                running_balance = opening_balance
                continue

            if "RULAJ ZI" in row.text:
                flush()
                continue

            if "SOLD FINAL ZI" in row.text:
                flush()
                m = re.search(r"(\d+(?:,\d{3})*\.\d{2})", row.text)
                if not m:
                    raise StatementExtractionError(f"nu pot citi SOLD FINAL ZI: {row.text!r}")
                day_end = _to_decimal(m.group(1))
                if running_balance is None or running_balance != day_end:
                    raise StatementExtractionError(
                        f"sold calculat ({running_balance}) != SOLD FINAL ZI raportat "
                        f"({day_end}) dupa {current_date} — extragerea a gresit ceva, "
                        "nu continui cu date posibil corupte"
                    )
                continue

            # E randul care deschide o tranzactie noua (are suma in banda
            # Debit/Credit) sau un rand de continuare (detalii/REF, fara suma)?
            amount_word_obj = None
            amount_side: str | None = None
            for w in row.words:
                token = str(w["text"])
                if not _AMOUNT_RE.match(token):
                    continue
                x0 = float(w["x0"])
                if debit_x0 is not None and abs(x0 - debit_x0) < _AMOUNT_X_TOLERANCE:
                    amount_word_obj, amount_side = w, "debit"
                elif credit_x0 is not None and abs(x0 - credit_x0) < _AMOUNT_X_TOLERANCE:
                    amount_word_obj, amount_side = w, "credit"

            if amount_word_obj is None:
                # continuare a tranzactiei curente (REF, detalii multi-linie)
                if row.text:
                    pending_continuation.append(row.text)
                continue

            # rand nou de tranzactie: inchide tranzactia anterioara, incepe una noua
            flush()
            date_word_obj = None
            for w in row.words:
                if _DATE_RE.match(str(w["text"])):
                    date_word_obj = w
                    break
            if date_word_obj is not None:
                m = _DATE_RE.match(str(date_word_obj["text"]))
                assert m is not None
                current_date = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"

            if running_balance is None or current_date is None:
                raise StatementExtractionError(
                    f"tranzactie gasita inainte de SOLD ANTERIOR sau fara data: {row.text!r}"
                )

            base_desc = " ".join(
                str(w["text"])
                for w in row.words
                if w is not amount_word_obj and w is not date_word_obj
            ).strip()
            pending_txn = _PendingTxn(
                date=current_date,
                base_desc=base_desc,
                amount_word=str(amount_word_obj["text"]),
                amount_side=amount_side or "debit",
            )
        if stopped:
            break

    flush()
    if opening_balance is None:
        raise StatementExtractionError("nu am gasit SOLD ANTERIOR in PDF — format neasteptat")
    return rows_out


def extract_transactions(pdf_path: Path) -> list[dict[str, str]]:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [
            _cluster_rows(page.extract_words(x_tolerance=1, y_tolerance=3)) for page in pdf.pages
        ]
    return _extract_from_pages(pages)


def convert(pdf_path: Path, csv_path: Path) -> int:
    transactions = extract_transactions(pdf_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["Data", "Descriere", "Suma Debit", "Suma Credit", "Sold"]
        )
        writer.writeheader()
        writer.writerows(transactions)
    return len(transactions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    count = convert(args.pdf_path, args.csv_path)
    print(f"OK: {count} tranzactii scrise in {args.csv_path}")


if __name__ == "__main__":
    main()
