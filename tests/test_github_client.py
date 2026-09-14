"""Unit tests for GitHubClient: HTTP mocked via httpx.MockTransport, no real
network calls and no `integration` marker needed — unlike ingestion/parsers/*,
this client's only I/O is HTTP, which MockTransport replaces cleanly at the
transport layer (no monkeypatching internals).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ingestion.github.client import GitHubClient, GitHubRateLimitError
from ingestion.github.config import GitHubConfig


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> GitHubClient:
    config = GitHubConfig(token="t", username="octocat", commits_since=None)
    client = GitHubClient(config)
    client._http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    return client


def _json_response(payload: object, link: str | None = None) -> httpx.Response:
    headers = {"Link": link} if link else {}
    return httpx.Response(200, json=payload, headers=headers)


_REPO_PAYLOAD = {
    "id": 1,
    "full_name": "octocat/dataforge",
    "name": "dataforge",
    "private": True,
    "fork": False,
    "language": "Python",
    "created_at": "2026-01-01T00:00:00Z",
    "pushed_at": "2026-02-01T00:00:00Z",
}


def test_list_repositories_happy_path() -> None:
    client = _client(lambda request: _json_response([_REPO_PAYLOAD]))

    result = client.list_repositories()

    assert result.errors == []
    assert len(result.records) == 1
    repo = result.records[0]
    assert repo.repo_id == 1
    assert repo.full_name == "octocat/dataforge"
    assert repo.is_private is True
    assert repo.is_fork is False


def test_list_repositories_follows_pagination_link_header() -> None:
    pages = [
        _json_response(
            [_REPO_PAYLOAD],
            link='<https://api.github.com/users/octocat/repos?page=2>; rel="next"',
        ),
        _json_response([{**_REPO_PAYLOAD, "id": 2, "full_name": "octocat/second"}]),
    ]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return pages[len(calls) - 1]

    client = _client(handler)

    result = client.list_repositories()

    assert len(calls) == 2
    assert [r.full_name for r in result.records] == ["octocat/dataforge", "octocat/second"]


def test_list_repositories_isolates_malformed_record() -> None:
    good = _REPO_PAYLOAD
    bad = {**_REPO_PAYLOAD, "id": 2, "full_name": "   "}  # fails _not_blank validator
    client = _client(lambda request: _json_response([good, bad]))

    result = client.list_repositories()

    assert len(result.records) == 1
    assert result.records[0].full_name == "octocat/dataforge"
    assert len(result.errors) == 1
    assert result.errors[0].endpoint == "repos"


def test_list_commits_falls_back_when_github_author_missing() -> None:
    payload = {
        "sha": "abc123",
        "commit": {"author": {"name": "Radu", "date": "2026-01-01T00:00:00Z"}, "message": "fix"},
        "author": None,
    }
    client = _client(lambda request: _json_response([payload]))

    result = client.list_commits("octocat/dataforge")

    assert result.errors == []
    commit = result.records[0]
    assert commit.author_login is None
    assert commit.author_name == "Radu"
    assert commit.repo_full_name == "octocat/dataforge"


def test_list_pull_requests_happy_path() -> None:
    payload = {
        "id": 10,
        "number": 1,
        "state": "closed",
        "title": "feat: something",
        "user": {"login": "octocat"},
        "created_at": "2026-01-01T00:00:00Z",
        "merged_at": "2026-01-02T00:00:00Z",
        "closed_at": "2026-01-02T00:00:00Z",
    }
    client = _client(lambda request: _json_response([payload]))

    result = client.list_pull_requests("octocat/dataforge")

    assert result.errors == []
    pr = result.records[0]
    assert pr.number == 1
    assert pr.author_login == "octocat"
    assert pr.merged_at is not None


def test_transient_transport_error_is_retried_until_success() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return _json_response([_REPO_PAYLOAD])

    client = _client(handler)

    result = client.list_repositories()

    assert attempts["count"] == 2
    assert len(result.records) == 1


def test_rate_limit_error_from_primary_limit_reads_reset_header() -> None:
    reset_epoch = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    response = httpx.Response(
        403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_epoch)},
        request=httpx.Request("GET", "https://api.github.com/x"),
    )

    error = GitHubClient._rate_limit_error_from(response)

    assert isinstance(error, GitHubRateLimitError)
    assert abs((error.reset_at - datetime.fromtimestamp(reset_epoch, tz=UTC)).total_seconds()) < 1


def test_rate_limit_error_from_secondary_limit_reads_retry_after_header() -> None:
    response = httpx.Response(
        403,
        headers={"Retry-After": "30"},
        request=httpx.Request("GET", "https://api.github.com/x"),
    )

    error = GitHubClient._rate_limit_error_from(response)

    assert isinstance(error, GitHubRateLimitError)
    seconds_left = (error.reset_at - datetime.now(UTC)).total_seconds()
    assert 25 < seconds_left <= 30


def test_rate_limit_error_from_plain_403_raises_http_status_error() -> None:
    response = httpx.Response(
        403,
        headers={},
        request=httpx.Request("GET", "https://api.github.com/x"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        GitHubClient._rate_limit_error_from(response)
