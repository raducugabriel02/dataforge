from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator


class RawActivity(BaseModel):
    activity_id: int
    activity_date: datetime
    name: str
    activity_type: str
    elapsed_time_seconds: int
    distance_meters: Decimal
    moving_time_seconds: int | None
    average_heart_rate: Decimal | None
    max_heart_rate: Decimal | None
    calories: Decimal | None

    @field_validator("name", "activity_type")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("cannot be blank")
        return v


@dataclass
class RowParseError:
    line_number: int
    raw_row: list[str]
    message: str


@dataclass
class ParseResult:
    activities: list[RawActivity] = field(default_factory=list)
    errors: list[RowParseError] = field(default_factory=list)
