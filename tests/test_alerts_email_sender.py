"""Unit tests for EmailSender: smtplib.SMTP is monkeypatched, no real network
or mail server involved — mirrors the best-effort contract itself, not
whether Gmail's SMTP actually accepts the credentials (unverifiable here).
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

from ingestion.alerts.config import AlertConfig
from ingestion.alerts.email_sender import EmailSender


def _config(**overrides: Any) -> AlertConfig:
    defaults: dict[str, Any] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "me@example.com",
        "smtp_password": "secret",
        "email_to": "me@example.com",
        "low_balance_threshold_ron": 200.0,
        "large_transaction_threshold_ron": 1000.0,
    }
    return AlertConfig(**{**defaults, **overrides})


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.sent_message: Any = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent_message = message


class _RaisingSMTP:
    def __init__(self, host: str, port: int, timeout: int) -> None:
        pass

    def __enter__(self) -> _RaisingSMTP:
        raise ConnectionRefusedError("smtp down")

    def __exit__(self, *exc_info: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_fake_smtp() -> None:
    _FakeSMTP.instances.clear()


def test_send_skips_when_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config(smtp_user="", smtp_password=""))

    sender.send("subject", "body")

    assert _FakeSMTP.instances == []


def test_send_skips_when_email_to_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config(email_to=""))

    sender.send("subject", "body")

    assert _FakeSMTP.instances == []


def test_send_delivers_message_with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config())

    sender.send("Alerta buget", "Ai depasit bugetul.")

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.starttls_called is True
    assert smtp.login_args == ("me@example.com", "secret")
    assert smtp.sent_message["Subject"] == "Alerta buget"
    assert smtp.sent_message["To"] == "me@example.com"


def test_send_swallows_smtp_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _RaisingSMTP)
    sender = EmailSender(_config())

    sender.send("subject", "body")  # must not raise
