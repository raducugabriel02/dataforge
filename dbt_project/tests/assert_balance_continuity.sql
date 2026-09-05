{#
    For each bank, ordered by the CSV's own row order (not txn_date, which
    only has day granularity and can't break ties within a day): the
    previous row's balance_after plus this row's amount must equal this
    row's own balance_after. A dbt test passes when this query returns zero
    rows, so any row that fails the invariant shows up as a failure.
#}

with ordered as (
    select
        source_bank,
        _source_row_number,
        amount,
        balance_after,
        lag(balance_after) over (
            partition by source_bank order by _source_row_number
        ) as previous_balance
    from {{ ref('stg_bank__transactions') }}
)

select *
from ordered
where previous_balance is not null
  and round(previous_balance + amount, 2) != round(balance_after, 2)
