"""Thin GitHub REST API client: pagination + rate-limit-aware retry.

Kept separate from ingestion/parsers/*: those parse a static local file with
no HTTP concerns; this walks a paginated, rate-limited API. Forcing both
through one abstract base would blur two genuinely different contracts.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingestion.github.config import GitHubConfig
from ingestion.github.models import (
    ExtractResult,
    RawCommit,
    RawPullRequest,
    RawRepository,
    RecordParseError,
)

_API_BASE = "https://api.github.com"
_PER_PAGE = 100


class GitHubRateLimitError(Exception):
    """Raised on GitHub's primary (quota exhausted) or secondary (abuse
    detection) rate limit. Carries the exact moment the caller may retry,
    read from response headers, so the retry wait sleeps precisely instead
    of guessing with blind exponential backoff.
    """

    def __init__(self, reset_at: datetime) -> None:
        super().__init__(f"GitHub rate limit hit, resets at {reset_at.isoformat()}")
        self.reset_at = reset_at


def _wait_for_rate_limit_reset(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, GitHubRateLimitError):
        seconds_left = (exc.reset_at - datetime.now(UTC)).total_seconds()
        return max(seconds_left, 1.0)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


class GitHubClient:
    def __init__(self, config: GitHubConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=_API_BASE,
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def list_repositories(self) -> ExtractResult[RawRepository]:
        result: ExtractResult[RawRepository] = ExtractResult()
        params = {"type": "owner", "sort": "full_name"}
        for raw in self._get_paginated(f"/users/{self._config.username}/repos", params):
            try:
                result.records.append(
                    RawRepository(
                        repo_id=raw["id"],
                        full_name=raw["full_name"],
                        name=raw["name"],
                        is_private=raw["private"],
                        is_fork=raw["fork"],
                        language=raw["language"],
                        created_at=raw["created_at"],
                        pushed_at=raw["pushed_at"],
                    )
                )
            except (ValidationError, KeyError) as exc:
                result.errors.append(RecordParseError("repos", raw, str(exc)))
        return result

    def list_commits(self, repo_full_name: str) -> ExtractResult[RawCommit]:
        result: ExtractResult[RawCommit] = ExtractResult()
        params = {"author": self._config.username}
        if self._config.commits_since:
            params["since"] = self._config.commits_since
        for raw in self._get_paginated(f"/repos/{repo_full_name}/commits", params):
            try:
                commit = raw["commit"]
                commit_author = commit.get("author") or {}
                github_author = raw.get("author") or {}
                result.records.append(
                    RawCommit(
                        sha=raw["sha"],
                        repo_full_name=repo_full_name,
                        author_login=github_author.get("login"),
                        author_name=commit_author.get("name"),
                        committed_at=commit_author["date"],
                        message=commit["message"],
                    )
                )
            except (ValidationError, KeyError) as exc:
                result.errors.append(RecordParseError(f"commits/{repo_full_name}", raw, str(exc)))
        return result

    def list_pull_requests(self, repo_full_name: str) -> ExtractResult[RawPullRequest]:
        result: ExtractResult[RawPullRequest] = ExtractResult()
        params = {"state": "all", "sort": "created", "direction": "asc"}
        for raw in self._get_paginated(f"/repos/{repo_full_name}/pulls", params):
            try:
                pr_author = raw.get("user") or {}
                result.records.append(
                    RawPullRequest(
                        pr_id=raw["id"],
                        number=raw["number"],
                        repo_full_name=repo_full_name,
                        state=raw["state"],
                        title=raw["title"],
                        author_login=pr_author.get("login"),
                        created_at=raw["created_at"],
                        merged_at=raw["merged_at"],
                        closed_at=raw["closed_at"],
                    )
                )
            except (ValidationError, KeyError) as exc:
                result.errors.append(RecordParseError(f"pulls/{repo_full_name}", raw, str(exc)))
        return result

    def _get_paginated(self, path: str, params: dict[str, str]) -> Iterator[dict[str, Any]]:
        url: str | None = path
        query: dict[str, str] | None = {**params, "per_page": str(_PER_PAGE)}
        while url is not None:
            response = self._request(url, query)
            page = response.json()
            logger.bind(url=str(response.url), page_size=len(page)).debug("github_page_fetched")
            yield from page
            # The "next" URL from the Link header already carries every
            # query param (including page=N+1), so params are not repeated.
            url = response.links.get("next", {}).get("url")
            query = None

    @retry(
        retry=retry_if_exception_type((GitHubRateLimitError, httpx.TransportError)),
        stop=stop_after_attempt(5),
        wait=_wait_for_rate_limit_reset,
        reraise=True,
    )
    def _request(self, url: str, params: dict[str, str] | None) -> httpx.Response:
        response = self._http.get(url, params=params)
        if response.status_code == 403:
            raise self._rate_limit_error_from(response)
        response.raise_for_status()
        return response

    @staticmethod
    def _rate_limit_error_from(response: httpx.Response) -> GitHubRateLimitError:
        if response.headers.get("X-RateLimit-Remaining") == "0":
            reset_epoch = int(response.headers["X-RateLimit-Reset"])
            return GitHubRateLimitError(datetime.fromtimestamp(reset_epoch, tz=UTC))
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            reset_at = datetime.now(UTC) + timedelta(seconds=int(retry_after))
            return GitHubRateLimitError(reset_at)
        # A plain 403 (e.g. bad token) is not a rate limit — surface it as-is.
        response.raise_for_status()
        raise AssertionError("unreachable: raise_for_status() always raises on a 403")
