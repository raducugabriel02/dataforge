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

-- Soldul la ULTIMA tranzactie cunoscuta a fiecarei banci, din fiecare luna
-- in care a existat macar o miscare. Ordonam intai dupa txn_date (data
-- calendaristica reala), apoi dupa _source_row_number ca tie-break in
-- cadrul aceleiasi zile — spre deosebire de assert_balance_continuity.sql,
-- care ordoneaza doar dupa _source_row_number pe intreg istoricul unei
-- banci (corect doar cat timp exista un singur extras incarcat per banca
-- pana acum; aici avem nevoie de cronologia reala pentru a grupa pe luna).
ranked as (
    select
        *,
        row_number() over (
            partition by source_bank, month_start
            order by txn_date desc, _source_row_number desc
        ) as rn
    from bucketed
),

actual_eom as (
    select
        source_bank,
        month_start,
        cast(balance_after as numeric(14, 2)) as balance_eom
    from ranked
    where rn = 1
),

bank_ranges as (
    select
        source_bank,
        min(month_start) as first_month,
        max(month_start) as last_month
    from actual_eom
    group by source_bank
),

month_spine as (
    select distinct date_trunc('month', date_day)::date as month_start
    from dim_date
),

-- Grain dens: fiecare banca apare in FIECARE luna dintre prima si ultima ei
-- tranzactie, chiar si in lunile fara nicio miscare — altfel soldul acelei
-- banci ar "disparea" din net worth-ul total pentru o luna fara tranzactii,
-- desi banii inca exista in cont (periodic snapshot fact, nu transaction
-- fact: un rand per stare repetata la interval fix, nu per eveniment).
dense_grain as (
    select
        bank_ranges.source_bank,
        month_spine.month_start
    from bank_ranges
    join month_spine
        on month_spine.month_start between bank_ranges.first_month and bank_ranges.last_month
),

filled as (
    select
        dense_grain.source_bank,
        dense_grain.month_start,
        actual_eom.balance_eom,
        -- Gaps-and-islands forward-fill: count(balance_eom) sare peste
        -- NULL-uri, deci creste doar in lunile cu tranzactie reala — toate
        -- lunile goale de dupa impart acelasi numar de grup cu ultima luna
        -- reala, iar first_value in cadrul grupului (ordonat crescator) e
        -- chiar acea valoare reala, "dusa mai departe" pana la urmatoarea
        -- tranzactie. Postgres nu are IGNORE NULLS pe window functions —
        -- asta e echivalentul standard-SQL al lui.
        count(actual_eom.balance_eom) over (
            partition by dense_grain.source_bank order by dense_grain.month_start
        ) as fill_group
    from dense_grain
    left join actual_eom
        on dense_grain.source_bank = actual_eom.source_bank
        and dense_grain.month_start = actual_eom.month_start
)

select
    source_bank,
    month_start,
    cast(
        first_value(balance_eom) over (
            partition by source_bank, fill_group order by month_start
        ) as numeric(14, 2)
    ) as balance_eom_filled,
    balance_eom is null as is_forward_filled
from filled
order by month_start, source_bank
