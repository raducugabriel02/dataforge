"""Generate synthetic Romanian bank statement CSVs (BT, BCR, ING formats).

Produces realistic-looking fixtures for the ingestion pipeline so real
financial data never has to enter the repo (see CLAUDE.md rule #5).
Each bank writer deliberately mimics a different real-world quirk:
delimiter, column names, date format, debit/credit representation, and a
messy, bank-specific description string (so dbt staging has real
normalization work to do, not a no-op).
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

TxnKind = Literal["purchase", "salary", "transfer"]


@dataclass(frozen=True)
class Transaction:
    txn_date: date
    merchant: str  # clean canonical name/token, e.g. "LIDL"
    kind: TxnKind
    city: str
    card_last4: str
    amount: float  # negative = expense, positive = income
    balance_after: float


CATEGORIES: dict[str, list[str]] = {
    "groceries": ["LIDL", "KAUFLAND", "CARREFOUR", "MEGA IMAGE", "PROFI"],
    "utilities": ["ENGIE ROMANIA", "ELECTRICA FURNIZARE", "DIGI ROMANIA", "ORANGE ROMANIA"],
    "transport": ["OMV PETROM", "MOL ROMANIA", "STB SA", "UBER"],
    "dining": ["GLOVO", "TAZZ", "MCDONALDS", "STARBUCKS"],
    "entertainment": ["NETFLIX", "SPOTIFY", "CINEMA CITY", "STEAM"],
    "transfer": ["RO49AAAA1B31007593840000"],
    "income": ["ANGAJATOR SRL"],
}

AMOUNT_RANGES: dict[str, tuple[float, float]] = {
    "groceries": (20.0, 350.0),
    "utilities": (50.0, 450.0),
    "transport": (15.0, 250.0),
    "dining": (10.0, 150.0),
    "entertainment": (10.0, 60.0),
    "transfer": (50.0, 2000.0),
    "income": (3500.0, 6500.0),
}

ROMANIAN_CITIES = [
    "SUCEAVA",
    "IASI",
    "CLUJ NAPOCA",
    "BUCURESTI",
    "TIMISOARA",
    "CONSTANTA",
    "BRASOV",
]

EXPENSE_CATEGORIES = [c for c in CATEGORIES if c != "income"]
_KIND_BY_CATEGORY: dict[str, TxnKind] = {
    "transfer": "transfer",
    "income": "salary",
}


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return d.replace(year=year, month=month, day=1)


def _make_transaction(
    rng: random.Random, day: date, category: str, amount: float, balance: float
) -> Transaction:
    merchant = rng.choice(CATEGORIES[category])
    kind = _KIND_BY_CATEGORY.get(category, "purchase")
    return Transaction(
        txn_date=day,
        merchant=merchant,
        kind=kind,
        city=rng.choice(ROMANIAN_CITIES),
        card_last4=f"{rng.randint(1000, 9999)}",
        amount=amount,
        balance_after=balance,
    )


def _generate_transactions(
    rng: random.Random,
    start: date,
    months: int,
    starting_balance: float,
) -> list[Transaction]:
    txns: list[Transaction] = []
    balance = starting_balance
    end = _add_months(start, months)

    day = start
    while day < end:
        for _ in range(rng.choices([0, 1, 2, 3], weights=[55, 25, 15, 5])[0]):
            category = rng.choice(EXPENSE_CATEGORIES)
            low, high = AMOUNT_RANGES[category]
            amount = -round(rng.uniform(low, high), 2)
            balance = round(balance + amount, 2)
            txns.append(_make_transaction(rng, day, category, amount, balance))

        if day.day == 1:
            low, high = AMOUNT_RANGES["income"]
            amount = round(rng.uniform(low, high), 2)
            balance = round(balance + amount, 2)
            txns.append(_make_transaction(rng, day, "income", amount, balance))

        day += timedelta(days=1)

    return txns


def _bt_description(t: Transaction) -> str:
    if t.kind == "salary":
        return f"ORDIN PLATA SALARIU {t.merchant}"
    if t.kind == "transfer":
        return f"TRANSFER CATRE {t.merchant}"
    return f"POS {t.card_last4} {t.merchant} {t.city} RO"


def _bcr_description(t: Transaction) -> str:
    if t.kind == "salary":
        return f"INCASARE SALARIU {t.merchant}"
    if t.kind == "transfer":
        return f"PLATA TRANSFER {t.merchant}"
    return f"CUMPARARE CARD {t.merchant} {t.city}"


def _ing_description(t: Transaction) -> str:
    if t.kind == "salary":
        return f"SALARY PAYMENT {t.merchant}"
    if t.kind == "transfer":
        return f"TRANSFER TO {t.merchant}"
    return f"CARD PAYMENT {t.merchant} {t.city}"


def write_bt_csv(path: Path, txns: list[Transaction]) -> None:
    """BT-style: comma-separated, separate debit/credit columns."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["Data", "Descriere", "Suma Debit", "Suma Credit", "Sold"])
        for t in txns:
            debit = f"{-t.amount:.2f}" if t.amount < 0 else ""
            credit = f"{t.amount:.2f}" if t.amount > 0 else ""
            row = [
                t.txn_date.strftime("%d.%m.%Y"),
                _bt_description(t),
                debit,
                credit,
                f"{t.balance_after:.2f}",
            ]
            writer.writerow(row)


def write_bcr_csv(path: Path, txns: list[Transaction]) -> None:
    """BCR-style: semicolon-separated, single signed amount column."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Data tranzactie", "Detalii tranzactie", "Suma", "Sold final"])
        for t in txns:
            row = [
                t.txn_date.strftime("%d.%m.%Y"),
                _bcr_description(t),
                f"{t.amount:.2f}",
                f"{t.balance_after:.2f}",
            ]
            writer.writerow(row)


def write_ing_csv(path: Path, txns: list[Transaction]) -> None:
    """ING-style: comma-separated, ISO dates, English column names."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",")
        writer.writerow(["Booking Date", "Description", "Amount", "Balance After Transaction"])
        for t in txns:
            row = [
                t.txn_date.isoformat(),
                _ing_description(t),
                f"{t.amount:.2f}",
                f"{t.balance_after:.2f}",
            ]
            writer.writerow(row)


WRITERS = {
    "bt": ("bt_statement.csv", write_bt_csv),
    "bcr": ("bcr_statement.csv", write_bcr_csv),
    "ing": ("ing_statement.csv", write_ing_csv),
}


def generate(bank: str, months: int, output_dir: Path, seed: int, starting_balance: float) -> Path:
    if bank not in WRITERS:
        raise ValueError(f"Unknown bank '{bank}'. Choose one of {list(WRITERS)}.")

    rng = random.Random(seed)
    start = _add_months(date.today(), -months)
    txns = _generate_transactions(rng, start, months, starting_balance)

    filename, writer_fn = WRITERS[bank]
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    writer_fn(path, txns)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", choices=[*WRITERS, "all"], default="all")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--output-dir", type=Path, default=Path("data/sample"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--starting-balance", type=float, default=5000.0)
    args = parser.parse_args()

    banks = list(WRITERS) if args.bank == "all" else [args.bank]
    for bank in banks:
        path = generate(bank, args.months, args.output_dir, args.seed, args.starting_balance)
        print(f"[{bank}] wrote {path}")


if __name__ == "__main__":
    main()
