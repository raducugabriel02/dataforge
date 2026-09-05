from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    @classmethod
    def from_env(cls) -> PostgresConfig:
        return cls(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            dbname=os.environ["POSTGRES_DB"],
        )

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.dbname}"
        )
