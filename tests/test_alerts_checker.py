"""Unit tests for AlertChecker's message-formatting and aggregation logic.

_query talks directly to Postgres, so it's monkeypatched here rather than
hit for real — the balance-continuity/idempotency invariants it depends on
are already covered by dbt tests and test_raw_loader_integration.py; what's
untested so far is purely the alert-formatting logic itself.
"""

from __future__ import annotations

import pytest

from ingestion.alerts.checker import AlertChecker
from ingestion.config import PostgresConfig


@pytest.fixture
def checker() -> AlertChecker:
    config = PostgresConfig(host="x", port=5432, user="x", password="x", dbname="x")
    return AlertChecker(
        config, low_balance_threshold_ron=200.0, large_transaction_threshold_ron=1000.0
    )


def test_over_budget_categories_formats_message(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checker,
        "_query",
        lambda sql, params=None: [
            {
                "category_name": "groceries",
                "monthly_budget_ron": 1500.0,
                "actual_spending": 1650.5,
                "pct_of_budget": 110.0,
            }
        ],
    )

    alerts = checker._over_budget_categories()

    assert alerts == ["Categoria 'groceries' e peste buget: 1650.50 RON din 1500.00 RON (110%)"]


def test_over_budget_categories_empty_returns_no_alerts(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "_query", lambda sql, params=None: [])

    assert checker._over_budget_categories() == []


def test_low_balance_accounts_below_threshold_alerts(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checker,
        "_query",
        lambda sql, params=None: [{"source_bank": "bt", "balance_after": 150.0}],
    )

    alerts = checker._low_balance_accounts()

    assert alerts == ["Sold bt sub prag: 150.00 RON (prag 200.00 RON)"]


def test_low_balance_accounts_above_threshold_is_silent(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checker,
        "_query",
        lambda sql, params=None: [{"source_bank": "bt", "balance_after": 5000.0}],
    )

    assert checker._low_balance_accounts() == []


def test_large_transactions_formats_message(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checker,
        "_query",
        lambda sql, params=None: [
            {"source_bank": "bt", "description": "ELECTRONICE SRL", "amount": -1500.0}
        ],
    )

    alerts = checker._large_transactions()

    assert alerts == ["Tranzactie neobisnuit de mare la bt: 1500.00 RON — ELECTRONICE SRL"]


def test_check_all_aggregates_in_order(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "_over_budget_categories", lambda: ["over-budget"])
    monkeypatch.setattr(checker, "_low_balance_accounts", lambda: ["low-balance"])
    monkeypatch.setattr(checker, "_large_transactions", lambda: ["large-txn"])

    assert checker.check_all() == ["over-budget", "low-balance", "large-txn"]


def test_check_all_with_no_alerts_returns_empty_list(
    checker: AlertChecker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "_query", lambda sql, params=None: [])

    assert checker.check_all() == []
