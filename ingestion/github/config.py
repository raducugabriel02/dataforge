from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubConfig:
    token: str
    username: str
    # Optional ISO date (YYYY-MM-DD): bounds how far back commit history is
    # pulled. Left unset, every run walks each repo's full commit history —
    # fine for a personal-scale portfolio repo count, but a real 100x-scale
    # deployment would track a per-repo high-water mark instead (see
    # docs/interview-notes.md, "idempotency end-to-end").
    commits_since: str | None

    @classmethod
    def from_env(cls) -> GitHubConfig:
        # .env ships GITHUB_TOKEN/GITHUB_USERNAME present-but-empty by default
        # (see .env.example), so os.environ[...] alone wouldn't raise — an
        # empty token would otherwise surface later as a cryptic
        # httpx.LocalProtocolError("Illegal header value b'Bearer '")
        # instead of pointing at the actual missing config.
        token = os.environ["GITHUB_TOKEN"].strip()
        if not token:
            raise ValueError(
                "GITHUB_TOKEN is empty — add a fine-grained PAT to .env "
                "before running the GitHub pipeline."
            )
        username = os.environ["GITHUB_USERNAME"].strip()
        if not username:
            raise ValueError(
                "GITHUB_USERNAME is empty — set the GitHub account whose repos to ingest in .env."
            )
        return cls(
            token=token,
            username=username,
            commits_since=os.environ.get("GITHUB_COMMITS_SINCE") or None,
        )
