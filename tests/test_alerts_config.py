from __future__ import annotations

import pytest

from ingestion.alerts.config import AlertConfig

_ALL_ALERT_ENV_VARS = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "ALERT_EMAIL_TO",
    "LOW_BALANCE_THRESHOLD_RON",
    "LARGE_TRANSACTION_THRESHOLD_RON",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ALL_ALERT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_from_env_defaults_when_nothing_set() -> None:
    config = AlertConfig.from_env()

    assert config.smtp_host == "smtp.gmail.com"
    assert config.smtp_port == 587
    assert config.smtp_user == ""
    assert config.smtp_password == ""
    assert config.email_to == ""
    assert config.low_balance_threshold_ron == 200.0
    assert config.large_transaction_threshold_ron == 1000.0


def test_from_env_reads_and_strips_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", " me@example.com ")
    monkeypatch.setenv("SMTP_PASSWORD", " secret ")
    monkeypatch.setenv("ALERT_EMAIL_TO", " me@example.com ")
    monkeypatch.setenv("LOW_BALANCE_THRESHOLD_RON", "300")
    monkeypatch.setenv("LARGE_TRANSACTION_THRESHOLD_RON", "2000")

    config = AlertConfig.from_env()

    assert config.smtp_host == "smtp.example.com"
    assert config.smtp_port == 465
    assert config.smtp_user == "me@example.com"
    assert config.smtp_password == "secret"
    assert config.email_to == "me@example.com"
    assert config.low_balance_threshold_ron == 300.0
    assert config.large_transaction_threshold_ron == 2000.0
