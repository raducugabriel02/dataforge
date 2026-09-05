with transactions as (
    select * from {{ ref('stg_bank__transactions') }}
),

merchant_rules as (
    select * from {{ ref('merchant_rules') }}
),

-- one row per transaction, enriched with the merchant/category matched from
-- its description (may not have a match — left join, defaults applied below)
categorized as (
    select
        transactions.*,
        coalesce(rules.merchant_name, 'Unknown') as merchant_name,
        coalesce(rules.category_name, 'uncategorized') as category_name
    from transactions
    left join merchant_rules as rules
        on transactions.description ilike '%' || rules.pattern || '%'
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
