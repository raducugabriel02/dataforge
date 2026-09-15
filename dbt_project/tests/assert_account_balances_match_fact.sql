{#
    Recalculeaza independent (direct din stg_bank__transactions, nu din
    mart_account_balances insusi) soldul de sfarsit de luna pentru fiecare
    (banca, luna) cu tranzactie reala, apoi compara cu ce a produs mart-ul
    pentru acele luni reale (is_forward_filled = false — lunile "umplute
    inainte" nu au un sold raportat propriu de comparat). Un test care doar
    re-selecteaza din mart nu ar prinde o regresie in logica modelului —
    de-asta refacem calculul aici, la fel ca assert_balance_continuity.sql.
#}

with transactions as (
    select * from {{ ref('stg_bank__transactions') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

bucketed as (
    select
        transactions.source_bank,
        transactions.balance_after,
        transactions.txn_date,
        transactions._source_row_number,
        date_trunc('month', dim_date.date_day)::date as month_start
    from transactions
    join dim_date
        on transactions.txn_date = dim_date.date_day
),

ranked as (
    select
        *,
        row_number() over (
            partition by source_bank, month_start
            order by txn_date desc, _source_row_number desc
        ) as rn
    from bucketed
),

expected as (
    select
        source_bank,
        month_start,
        cast(balance_after as numeric(14, 2)) as expected_balance
    from ranked
    where rn = 1
),

actual as (
    select source_bank, month_start, balance_eom_filled
    from {{ ref('mart_account_balances') }}
    where not is_forward_filled
)

select
    actual.source_bank,
    actual.month_start,
    actual.balance_eom_filled,
    expected.expected_balance
from actual
join expected
    on actual.source_bank = expected.source_bank
    and actual.month_start = expected.month_start
where round(actual.balance_eom_filled, 2) != round(expected.expected_balance, 2)
