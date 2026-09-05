with snapshot as (
    select * from {{ ref('expense_categories_snapshot') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['category_name', 'dbt_valid_from']) }} as category_key,
    category_name,
    category_group,
    dbt_valid_from as valid_from,
    coalesce(dbt_valid_to, timestamp '9999-12-31') as valid_to,
    dbt_valid_to is null as is_current
from snapshot
