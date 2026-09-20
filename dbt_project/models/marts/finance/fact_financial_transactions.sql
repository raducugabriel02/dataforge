-- Incremental (unique_key: transaction_id, config in schema.yml): fiecare
-- rulare normala proceseaza doar tranzactiile noi, nu reconstruieste toata
-- tabela. Efect secundar de retinut: daca dim_expense_category se schimba
-- retroactiv (ex: capcana SCD2 valid_from din interview-notes.md), factul
-- deja materializat NU se recalculeaza singur — trebuie `dbt run --full-refresh
-- --select fact_financial_transactions` explicit. E comportamentul corect, nu
-- un bug: istoricul ramane fixat la ce era valid la momentul tranzactiei.
--
-- txn_date e pastrat ca si coloana literala (nu doar date_key, FK-ul surogat
-- spre dim_date) special pentru Semantic Layer: MetricFlow cere un
-- agg_time_dimension real (tip time) direct pe modelul semantic care are
-- metricile, nu poate deriva timpul doar dintr-un FK catre alt model.
with transactions as (
    select * from {{ ref('stg_bank__transactions') }}
),

merchant_rules as (
    select * from {{ ref('merchant_rules') }}
),

-- one row per transaction, enriched with the merchant/category matched from
-- its description (may not have a match — left join, defaults applied below).
-- O descriere reala poate contine mai multe pattern-uri deodata (ex: o linie
-- de comision care mentioneaza si numele platformei de pariuri) — fara sa
-- alegem un singur castigator determinist, tranzactia s-ar duplica aici
-- (fan-out pe left join), nu doar categorisi gresit. Vezi acelasi tie-break
-- (priority, apoi lungime pattern) ca in dim_merchant.sql.
matched as (
    select
        transactions.*,
        coalesce(rules.merchant_name, 'Unknown') as merchant_name,
        coalesce(rules.category_name, 'uncategorized') as category_name,
        row_number() over (
            partition by transactions.transaction_id
            order by coalesce(rules.priority, 999) asc, length(rules.pattern) desc
        ) as rn
    from transactions
    left join merchant_rules as rules
        on transactions.description ilike '%' || rules.pattern || '%'
),

categorized as (
    select * from matched where rn = 1
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

dim_merchant as (
    select * from {{ ref('dim_merchant') }}
),

dim_expense_category as (
    select * from {{ ref('dim_expense_category') }}
)

select
    categorized.transaction_id,
    categorized.txn_date,
    dim_date.date_key,
    dim_merchant.merchant_key,
    -- point-in-time SCD2 join: the category dimension row that was ACTIVE on
    -- the transaction's own date, not whatever the category looks like today
    dim_expense_category.category_key,
    categorized.source_bank,
    categorized.description,
    categorized.amount,
    categorized.balance_after,
    'RON' as currency
from categorized
left join dim_date
    on categorized.txn_date = dim_date.date_day
left join dim_merchant
    on categorized.merchant_name = dim_merchant.merchant_name
left join dim_expense_category
    on categorized.category_name = dim_expense_category.category_name
    and categorized.txn_date >= dim_expense_category.valid_from
    and categorized.txn_date < dim_expense_category.valid_to
{% if is_incremental() %}
where categorized.transaction_id not in (select transaction_id from {{ this }})
{% endif %}
