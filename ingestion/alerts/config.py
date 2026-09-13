from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AlertConfig:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_to: str
    low_balance_threshold_ron: float
    large_transaction_threshold_ron: float

    @classmethod
    def from_env(cls) -> AlertConfig:
        # SMTP-ul necompletat e un stare valida (la fel ca DISCORD_WEBHOOK_URL
        # in Faza 3): pipeline-ul tot ruleaza, EmailSender doar sare peste
        # trimitere si logheaza. Nu ridicam ValueError aici ca la GitHubConfig,
        # fiindca alertele nu sunt o precondifie a rularii, ci un extra.
        return cls(
            smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", "").strip(),
            smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
            email_to=os.environ.get("ALERT_EMAIL_TO", "").strip(),
            low_balance_threshold_ron=float(os.environ.get("LOW_BALANCE_THRESHOLD_RON", "200")),
            large_transaction_threshold_ron=float(
                os.environ.get("LARGE_TRANSACTION_THRESHOLD_RON", "1000")
            ),
        )
