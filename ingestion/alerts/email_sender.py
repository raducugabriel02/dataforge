from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage

from loguru import logger

from ingestion.alerts.checker import Alert, AlertCategory
from ingestion.alerts.config import AlertConfig

# emoji, titlu, culoare accent — in ordinea in care vrem sectiunile afisate,
# indiferent de ordinea in care check_all() le produce.
_CATEGORY_DISPLAY: dict[AlertCategory, tuple[str, str, str]] = {
    "buget": ("📊", "Depășiri de buget", "#b91c1c"),
    "sold": ("💰", "Sold scăzut", "#b45309"),
    "tranzactie_mare": ("🔺", "Tranzacții neobișnuite", "#6d28d9"),
}


def _alert_count_phrase(count: int, singular: str, plural: str) -> str:
    return f"1 alertă {singular}" if count == 1 else f"{count} alerte {plural}"


class EmailSender:
    """Trimitere best-effort, la fel ca notify_discord_failure din dags/common.py:
    o alerta nu trebuie sa opreasca pipeline-ul, deci prindem orice eroare si
    doar o logam. SMTP necompletat e o stare valida (vezi AlertConfig.from_env).
    """

    def __init__(self, config: AlertConfig) -> None:
        self._config = config

    def send_alerts(self, alerts: list[Alert]) -> None:
        has_credentials = self._config.smtp_user and self._config.smtp_password
        if not has_credentials or not self._config.email_to:
            logger.info("smtp_not_configured — sar peste trimiterea alertei")
            return

        subject = f"DataForge — {_alert_count_phrase(len(alerts), 'financiară', 'financiare')}"
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._config.smtp_user
        message["To"] = self._config.email_to
        message.set_content(_build_text_body(alerts))
        message.add_alternative(_build_html_body(alerts), subtype="html")

        try:
            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(self._config.smtp_user, self._config.smtp_password)
                smtp.send_message(message)
        except Exception as exc:  # pragma: no cover - notificare best-effort
            logger.bind(error=str(exc)).error("alert_email_send_failed")
            return

        logger.bind(to=self._config.email_to, subject=subject).info("alert_email_sent")


def _grouped_by_category(alerts: list[Alert]) -> list[tuple[str, str, str, list[str]]]:
    """Sectiuni in ordinea fixa din _CATEGORY_DISPLAY, nu in ordinea de aparitie
    din check_all() — asa un email cu doar tranzactii mari (ultima categorie
    verificata) nu pare "incomplet" fata de unul cu toate trei.
    """
    sections = []
    for category, (emoji, label, color) in _CATEGORY_DISPLAY.items():
        messages = [alert.message for alert in alerts if alert.category == category]
        if messages:
            sections.append((emoji, label, color, messages))
    return sections


def _build_text_body(alerts: list[Alert]) -> str:
    blocks = []
    for emoji, label, _color, messages in _grouped_by_category(alerts):
        lines = "\n".join(f"- {message}" for message in messages)
        blocks.append(f"{emoji} {label.upper()}\n{lines}")
    return "\n\n".join(blocks)


def _build_html_body(alerts: list[Alert]) -> str:
    sections_html = ""
    for emoji, label, color, messages in _grouped_by_category(alerts):
        items = "".join(f"<li>{html.escape(message)}</li>" for message in messages)
        sections_html += f"""
        <div style="margin-top:20px;">
          <div style="font-size:14px;font-weight:600;color:{color};margin-bottom:8px;">
            {emoji} {html.escape(label)}
          </div>
          <ul style="margin:0;padding-left:20px;color:#27272a;font-size:14px;line-height:1.6;">
            {items}
          </ul>
        </div>
        """

    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:24px;background:#f4f4f5;
               font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
    <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;
                overflow:hidden;border:1px solid #e4e4e7;">
      <div style="background:#18181b;color:#ffffff;padding:20px 24px;">
        <h1 style="margin:0;font-size:18px;">DataForge — Alerte financiare</h1>
        <p style="margin:4px 0 0;font-size:13px;color:#a1a1aa;">
          {html.escape(_alert_count_phrase(len(alerts), "declanșată", "declanșate"))}
        </p>
      </div>
      <div style="padding:8px 24px 24px;">
        {sections_html}
      </div>
      <div style="padding:16px 24px;border-top:1px solid #e4e4e7;
                  font-size:12px;color:#a1a1aa;">
        Acest email a fost generat automat de DataForge, platforma ta personală
        de urmărire financiară.
      </div>
    </div>
  </body>
</html>
"""
