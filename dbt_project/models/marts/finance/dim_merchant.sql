with transactions as (
    select * from {{ ref('stg_bank__transactions') }}
),

merchant_rules as (
    select * from {{ ref('merchant_rules') }}
),

-- o descriere reala poate contine mai multe pattern-uri deodata (ex: o linie
-- de comision care mentioneaza si numele platformei de pariuri) — pastram
-- doar cea mai prioritara potrivire per tranzactie (priority mic = castiga),
-- cu lungimea pattern-ului ca tie-break determinist, ca sa nu construim
-- perechi (merchant, categorie) care nu sunt de fapt alese de nicio tranzactie.
matched as (
    select
        transactions.transaction_id,
        coalesce(rules.merchant_name, 'Unknown') as merchant_name,
        coalesce(rules.category_name, 'uncategorized') as default_category_name,
        row_number() over (
            partition by transactions.transaction_id
            order by coalesce(rules.priority, 999) asc, length(rules.pattern) desc
        ) as rn
    from transactions
    left join merchant_rules as rules
        on transactions.description ilike '%' || rules.pattern || '%'
)

select distinct
    {{ dbt_utils.generate_surrogate_key(['merchant_name']) }} as merchant_key,
    merchant_name,
    default_category_name
from matched
where rn = 1
