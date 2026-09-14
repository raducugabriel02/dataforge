with fact as (
    select * from {{ ref('fact_financial_transactions') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

monthly as (
    select
        date_trunc('month', dim_date.date_day)::date as month_start,
        sum(case when fact.amount < 0 then -fact.amount else 0 end) as total_spending,
        sum(case when fact.amount > 0 then fact.amount else 0 end) as total_income
    from fact
    join dim_date
        on fact.date_key = dim_date.date_key
    group by 1
)

select
    month_start,
    cast(total_spending as numeric(14, 2)) as total_spending,
    cast(total_income as numeric(14, 2)) as total_income,
    cast(total_income - total_spending as numeric(14, 2)) as net_cashflow,
    cast(sum(total_spending) over (order by month_start) as numeric(14, 2)) as cumulative_spending,
    cast(
        avg(total_spending) over (
            order by month_start
            rows between 2 preceding and current row
        ) as numeric(14, 2)
    ) as rolling_3_month_avg,
    cast(
        total_spending - lag(total_spending) over (order by month_start) as numeric(14, 2)
    ) as delta_vs_previous_month
from monthly
order by month_start
