from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.generate_fake_bank_data import generate


def test_generate_bt_produces_valid_csv(tmp_path: Path) -> None:
    output_path = generate("bt", months=2, output_dir=tmp_path, seed=1, starting_balance=1000.0)

    assert output_path.exists()
    with output_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == ["Data", "Descriere", "Suma Debit", "Suma Credit", "Sold"]
    assert len(rows) > 0
    for row in rows:
        assert row["Descriere"]
        assert row["Sold"]


def test_generate_is_deterministic_with_seed(tmp_path: Path) -> None:
    path_a = generate("ing", months=1, output_dir=tmp_path / "a", seed=7, starting_balance=500.0)
    path_b = generate("ing", months=1, output_dir=tmp_path / "b", seed=7, starting_balance=500.0)

    assert path_a.read_text(encoding="utf-8") == path_b.read_text(encoding="utf-8")


def test_generate_rejects_unknown_bank(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate("revolut", months=1, output_dir=tmp_path, seed=1, starting_balance=0.0)


def test_running_balance_is_consistent(tmp_path: Path) -> None:
    output_path = generate("bcr", months=3, output_dir=tmp_path, seed=3, starting_balance=1000.0)

    with output_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    balance = 1000.0
    for row in rows:
        balance = round(balance + float(row["Suma"]), 2)
        assert balance == float(row["Sold final"])
