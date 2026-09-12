"""Helpers partajate intre DAG-uri (extrase la Faza 5, cand al doilea
pipeline a avut nevoie de exact aceeasi alerta Discord si acelasi format de
comanda dbt ca bank_pipeline.py — semn ca merita un modul comun, nu ca fiecare
DAG isi reimplementeaza propria varianta).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DBT_PROJECT_DIR = os.environ.get("DBT_PROJECT_DIR", "/opt/dataforge/dbt_project")


def notify_discord_failure(context: dict[str, Any]) -> None:
    """default_args on_failure_callback: trimite o alerta pe Discord daca orice
    task din DAG esueaza. Best-effort — o eroare la trimitere nu trebuie sa
    ascunda eroarea reala a pipeline-ului, deci doar loghez, nu ridic exceptie.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL nesetat — sar peste notificare")
        return

    task_instance = context["task_instance"]
    payload = {
        "content": (
            f"🔴 **{context['dag'].dag_id}** a esuat pe task `{task_instance.task_id}` "
            f"(run `{context['run_id']}`)\n{task_instance.log_url}"
        )
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except Exception as exc:  # pragma: no cover - notificare best-effort
        print(f"Trimiterea notificarii Discord a esuat: {exc}")


def dbt_command(subcommand: str, *tags: str) -> str:
    """Comanda dbt filtrata pe unul sau mai multe tag-uri (union — un tag e
    de-ajuns ca un model sa fie inclus). github_pipeline foloseste doi tag-uri
    (`github` + `combined`) ca sa reconstruiasca si mart-ul finante x
    productivitate dupa ce ingereaza sursa mai noua.
    """
    select_expr = " ".join(f"tag:{tag}" for tag in tags)
    return (
        f"dbt {subcommand} --select {select_expr} "
        f"--project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROJECT_DIR}"
    )
