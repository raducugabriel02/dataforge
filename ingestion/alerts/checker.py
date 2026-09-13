from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from ingestion.config import PostgresConfig

_OVER_BUDGET_SQL = """
    select category_name, monthly_budget_ron, actual_spending, pct_of_budget
    from marts.mart_budget_alerts
    where is_over_budget
      and month_start = date_trunc('month', current_date)::date
    order by category_name
"""

# distinct on + order by _source_row_number desc: ultima tranzactie a fiecarei
# banci in ordinea propriului extras, nu dupa txn_date — vezi comentariul din
# assert_balance_continuity.sql, soldul e continuu doar per banca, in ordinea
# randurilor din CSV.
_LATEST_BALANCE_SQL = """
    select distinct on (source_bank) source_bank, balance_after
    from staging.stg_bank__transactions
    order by source_bank, _source_row_number desc
"""

_LARGE_TRANSACTIONS_SQL = """
    select source_bank, description, amount
    from staging.stg_bank__transactions
    where amount < 0
      and -amount > %(threshold)s
      and txn_date = current_date
    order by amount
"""


class AlertChecker:
    """Trei verificari punctuale peste marts/staging existente. Primele doua
    praguri (sold, tranzactie mare) sunt query-uri SQL simple, nu modele dbt —
    sunt verificari operationale, nu agregari dimensionale reutilizabile (spre
    deosebire de mart_budget_alerts, care e o agregare pe grain categorie x luna).
    """

    def __init__(
        self,
        config: PostgresConfig,
        low_balance_threshold_ron: float,
        large_transaction_threshold_ron: float,
    ) -> None:
        self._config = config
        self._low_balance_threshold_ron = low_balance_threshold_ron
        self._large_transaction_threshold_ron = large_transaction_threshold_ron

    def check_all(self) -> list[str]:
        return [
            *self._over_budget_categories(),
            *self._low_balance_accounts(),
            *self._large_transactions(),
        ]

    def _over_budget_categories(self) -> list[str]:
        rows = self._query(_OVER_BUDGET_SQL)
        return [
            f"Categoria '{row['category_name']}' e peste buget: "
            f"{row['actual_spending']:.2f} RON din {row['monthly_budget_ron']:.2f} RON "
            f"({row['pct_of_budget']:.0f}%)"
            for row in rows
        ]

    def _low_balance_accounts(self) -> list[str]:
        rows = self._query(_LATEST_BALANCE_SQL)
        alerts = []
        for row in rows:
            balance = float(row["balance_after"])  # type: ignore[arg-type]
            if balance < self._low_balance_threshold_ron:
                alerts.append(
                    f"Sold {row['source_bank']} sub prag: {balance:.2f} RON "
                    f"(prag {self._low_balance_threshold_ron:.2f} RON)"
                )
        return alerts

    def _large_transactions(self) -> list[str]:
        rows = self._query(
            _LARGE_TRANSACTIONS_SQL, {"threshold": self._large_transaction_threshold_ron}
        )
        return [
            f"Tranzactie neobisnuit de mare la {row['source_bank']}: "
            f"{-float(row['amount']):.2f} RON — {row['description']}"  # type: ignore[arg-type]
            for row in rows
        ]

    def _query(
        self, sql: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        with (
            psycopg.connect(self._config.dsn, row_factory=dict_row) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(sql, params)
            return cur.fetchall()
