with fact as (
    select * from {{ ref('fact_financial_transactions') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

dim_expense_category as (
    select * from {{ ref('dim_expense_category') }}
),

budgets as (
    select * from {{ ref('category_budgets') }}
),

monthly_spend as (
    select
        dim_expense_category.category_name,
        date_trunc('month', dim_date.date_day)::date as month_start,
        sum(case when fact.amount < 0 then -fact.amount else 0 end) as actual_spending
    from fact
    join dim_date
        on fact.date_key = dim_date.date_key
    join dim_expense_category
        on fact.category_key = dim_expense_category.category_key
    group by 1, 2
)

-- inner join: doar categoriile cu buget definit apar aici — asta e mart-ul
-- de alerte, nu unul de raportare generala (acela e mart_monthly_spending).
select
    monthly_spend.category_name,
    monthly_spend.month_start,
    budgets.monthly_budget_ron,
    monthly_spend.actual_spending,
    monthly_spend.actual_spending > budgets.monthly_budget_ron as is_over_budget,
    round(monthly_spend.actual_spending / budgets.monthly_budget_ron * 100, 1) as pct_of_budget
from monthly_spend
join budgets
    on monthly_spend.category_name = budgets.category_name
order by month_start, category_name
