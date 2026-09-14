from __future__ import annotations

import pytest

from ingestion.github.config import GitHubConfig


def test_from_env_reads_required_and_optional_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", " ghp_abc ")
    monkeypatch.setenv("GITHUB_USERNAME", " octocat ")
    monkeypatch.setenv("GITHUB_COMMITS_SINCE", "2026-01-01")

    config = GitHubConfig.from_env()

    assert config.token == "ghp_abc"
    assert config.username == "octocat"
    assert config.commits_since == "2026-01-01"


def test_from_env_commits_since_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc")
    monkeypatch.setenv("GITHUB_USERNAME", "octocat")
    monkeypatch.delenv("GITHUB_COMMITS_SINCE", raising=False)

    config = GitHubConfig.from_env()

    assert config.commits_since is None


def test_from_env_raises_on_blank_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    monkeypatch.setenv("GITHUB_USERNAME", "octocat")

    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        GitHubConfig.from_env()


def test_from_env_raises_on_blank_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc")
    monkeypatch.setenv("GITHUB_USERNAME", "   ")

    with pytest.raises(ValueError, match="GITHUB_USERNAME"):
        GitHubConfig.from_env()


def test_from_env_raises_on_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_USERNAME", "octocat")

    with pytest.raises(KeyError):
        GitHubConfig.from_env()
