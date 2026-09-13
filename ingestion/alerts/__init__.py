from __future__ import annotations

from loguru import logger

from ingestion.alerts.checker import AlertChecker
from ingestion.alerts.config import AlertConfig
from ingestion.alerts.email_sender import EmailSender
from ingestion.config import PostgresConfig


def run_and_notify() -> str:
    """Ruleaza toate verificarile si trimite UN singur email consolidat daca
    macar una a fost declansata. Idempotenta simpla: re-alertam in fiecare
    rulare zilnica cat timp conditia ramane adevarata — nu tinem stare
    persistenta de "am mai alertat pe asta", ar fi supra-inginerie pentru
    un DAG care oricum ruleaza o data pe zi.
    """
    postgres_config = PostgresConfig.from_env()
    alert_config = AlertConfig.from_env()

    checker = AlertChecker(
        postgres_config,
        low_balance_threshold_ron=alert_config.low_balance_threshold_ron,
        large_transaction_threshold_ron=alert_config.large_transaction_threshold_ron,
    )
    messages = checker.check_all()

    if not messages:
        logger.info("no_alerts_triggered")
        return "0 alerte declansate"

    body = "\n".join(f"- {message}" for message in messages)
    EmailSender(alert_config).send(
        subject=f"DataForge — {len(messages)} alerta(e) financiara(e)",
        body=body,
    )
    return f"{len(messages)} alerte trimise: " + "; ".join(messages)
