"""Unit tests for dags/common.py — previously only verified live in the real
Airflow container (Faza 5/6 DAG runs), never covered by an automated test.
No airflow import needed: the module is deliberately plain stdlib, so it's
testable without airflow installed in this environment.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from unittest.mock import MagicMock

import pytest

from dags import common


def test_dbt_command_filters_by_single_tag() -> None:
    command = common.dbt_command("run", "bank")

    assert command == (
        "dbt run --select tag:bank "
        f"--project-dir {common.DBT_PROJECT_DIR} --profiles-dir {common.DBT_PROJECT_DIR}"
    )


def test_dbt_command_unions_multiple_tags() -> None:
    command = common.dbt_command("test", "github", "combined")

    assert "--select tag:github tag:combined" in command


def _failure_context(dag_id: str = "bank_pipeline", task_id: str = "dbt_test") -> dict[str, Any]:
    task_instance = MagicMock()
    task_instance.task_id = task_id
    task_instance.log_url = "http://airflow.local/log"
    dag = MagicMock()
    dag.dag_id = dag_id
    return {"task_instance": task_instance, "dag": dag, "run_id": "manual__2026-09-28"}


def test_notify_discord_failure_skips_when_webhook_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    urlopen_mock = MagicMock()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen_mock)

    common.notify_discord_failure(_failure_context())

    urlopen_mock.assert_not_called()


def test_notify_discord_failure_posts_dag_and_task_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example.com/webhook")
    urlopen_mock = MagicMock()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen_mock)

    common.notify_discord_failure(_failure_context(dag_id="strava_pipeline", task_id="dbt_test"))

    urlopen_mock.assert_called_once()
    request = urlopen_mock.call_args[0][0]
    assert request.full_url == "https://discord.example.com/webhook"
    payload = json.loads(request.data.decode("utf-8"))
    assert "strava_pipeline" in payload["content"]
    assert "dbt_test" in payload["content"]
    assert "http://airflow.local/log" in payload["content"]


def test_notify_discord_failure_swallows_send_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example.com/webhook")

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError("discord unreachable")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)

    common.notify_discord_failure(_failure_context())  # must not raise
