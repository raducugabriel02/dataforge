from __future__ import annotations

import smtplib
from email.message import EmailMessage

from loguru import logger

from ingestion.alerts.config import AlertConfig


class EmailSender:
    """Trimitere best-effort, la fel ca notify_discord_failure din dags/common.py:
    o alerta nu trebuie sa opreasca pipeline-ul, deci prindem orice eroare si
    doar o logam. SMTP necompletat e o stare valida (vezi AlertConfig.from_env).
    """

    def __init__(self, config: AlertConfig) -> None:
        self._config = config

    def send(self, subject: str, body: str) -> None:
        has_credentials = self._config.smtp_user and self._config.smtp_password
        if not has_credentials or not self._config.email_to:
            logger.info("smtp_not_configured — sar peste trimiterea alertei")
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._config.smtp_user
        message["To"] = self._config.email_to
        message.set_content(body)

        try:
            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(self._config.smtp_user, self._config.smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - notificare best-effort
            logger.bind(error=str(exc)).error("alert_email_send_failed")
            return

        logger.bind(to=self._config.email_to, subject=subject).info("alert_email_sent")
