from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator


class ParsedTransaction(BaseModel):
    txn_date: date
    description: str
    amount: Decimal
    balance_after: Decimal
    source_bank: str

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("description cannot be blank")
        return v
