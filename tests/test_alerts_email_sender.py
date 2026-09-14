"""Unit tests for EmailSender: smtplib.SMTP is monkeypatched, no real network
or mail server involved — mirrors the best-effort contract itself, not
whether Gmail's SMTP actually accepts the credentials (unverifiable here).
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest

from ingestion.alerts.checker import Alert
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


_SAMPLE_ALERTS = [
    Alert(category="buget", message="Categoria 'groceries' e peste buget: 1650.50 RON"),
    Alert(category="sold", message="Sold bt sub prag: 150.00 RON"),
]


def test_send_alerts_skips_when_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config(smtp_user="", smtp_password=""))

    sender.send_alerts(_SAMPLE_ALERTS)

    assert _FakeSMTP.instances == []


def test_send_alerts_skips_when_email_to_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config(email_to=""))

    sender.send_alerts(_SAMPLE_ALERTS)

    assert _FakeSMTP.instances == []


def test_send_alerts_delivers_html_and_text_grouped_by_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config())

    sender.send_alerts(_SAMPLE_ALERTS)

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.starttls_called is True
    assert smtp.login_args == ("me@example.com", "secret")
    message = smtp.sent_message
    assert message["Subject"] == "DataForge — 2 alerte financiare"
    assert message["To"] == "me@example.com"
    assert message.is_multipart()

    text_body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Categoria 'groceries' e peste buget: 1650.50 RON" in text_body
    assert "Sold bt sub prag: 150.00 RON" in text_body
    assert "DEPĂȘIRI DE BUGET" in text_body
    assert "SOLD SCĂZUT" in text_body

    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert "Categoria &#x27;groceries&#x27; e peste buget: 1650.50 RON" in html_body
    assert "Depășiri de buget" in html_body
    assert "Sold scăzut" in html_body


def test_send_alerts_escapes_html_special_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config())
    alerts = [Alert(category="tranzactie_mare", message="AB & CO <script>alert(1)</script>")]

    sender.send_alerts(alerts)

    html_body = _FakeSMTP.instances[0].sent_message.get_body(
        preferencelist=("html",)
    ).get_content()
    assert "<script>" not in html_body
    assert "AB &amp; CO" in html_body


def test_send_alerts_subject_is_singular_for_one_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config())
    alerts = [Alert(category="sold", message="Sold BT sub prag: 150.00 RON")]

    sender.send_alerts(alerts)

    assert _FakeSMTP.instances[0].sent_message["Subject"] == "DataForge — 1 alertă financiară"


def test_send_alerts_footer_has_no_internal_jargon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    sender = EmailSender(_config())

    sender.send_alerts(_SAMPLE_ALERTS)

    html_body = _FakeSMTP.instances[0].sent_message.get_body(
        preferencelist=("html",)
    ).get_content()
    assert "bank_pipeline" not in html_body
    assert "check_alerts" not in html_body


def test_send_alerts_swallows_smtp_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _RaisingSMTP)
    sender = EmailSender(_config())

    sender.send_alerts(_SAMPLE_ALERTS)  # must not raise
