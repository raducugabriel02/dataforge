from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class RawRepository(BaseModel):
    repo_id: int
    full_name: str
    name: str
    is_private: bool
    is_fork: bool
    language: str | None
    created_at: datetime
    pushed_at: datetime | None

    @field_validator("full_name", "name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("cannot be blank")
        return v


class RawCommit(BaseModel):
    sha: str
    repo_full_name: str
    author_login: str | None
    author_name: str | None
    committed_at: datetime
    message: str


class RawPullRequest(BaseModel):
    pr_id: int
    number: int
    repo_full_name: str
    state: str
    title: str
    author_login: str | None
    created_at: datetime
    merged_at: datetime | None
    closed_at: datetime | None


@dataclass
class RecordParseError:
    endpoint: str
    raw_record: dict[str, Any]
    message: str


@dataclass
class ExtractResult[T]:
    records: list[T] = field(default_factory=list)
    errors: list[RecordParseError] = field(default_factory=list)
