with transactions as (
    select * from {{ ref('stg_bank__transactions') }}
),

merchant_rules as (
    select * from {{ ref('merchant_rules') }}
),

matched as (
    select distinct
        coalesce(rules.merchant_name, 'Unknown') as merchant_name,
        coalesce(rules.category_name, 'uncategorized') as default_category_name
    from transactions
    left join merchant_rules as rules
        on transactions.description ilike '%' || rules.pattern || '%'
)

select
    {{ dbt_utils.generate_surrogate_key(['merchant_name']) }} as merchant_key,
    merchant_name,
    default_category_name
from matched
