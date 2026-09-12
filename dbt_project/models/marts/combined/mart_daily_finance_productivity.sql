-- Grain: one row per calendar day, bounded by the overlap of activity across
-- both sources. Unlike fact_daily_productivity (sparse — only days with an
-- event), this is a dense spine on purpose: a day with zero commits AND zero
-- spending is still a meaningful data point once you're correlating the two
-- (e.g. "do I spend less on days I commit more?"), so zero-activity days
-- must appear as real zeros, not be missing rows.
with financial_transactions as (
    select * from {{ ref('fact_financial_transactions') }}
),

daily_productivity as (
    select * from {{ ref('fact_daily_productivity') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

daily_spending as (
    select
        dim_date.date_day,
        sum(case when financial_transactions.amount < 0 then -financial_transactions.amount else 0 end)
            as total_spending,
        count(*) as transaction_count
    from financial_transactions
    join dim_date on financial_transactions.date_key = dim_date.date_key
    group by 1
),

daily_productivity_agg as (
    select
        dim_date.date_day,
        sum(daily_productivity.commit_count) as commit_count,
        sum(daily_productivity.pr_opened_count) as pr_opened_count,
        sum(daily_productivity.pr_merged_count) as pr_merged_count
    from daily_productivity
    join dim_date on daily_productivity.date_key = dim_date.date_key
    group by 1
),

active_range as (
    select
        min(date_day) as range_start,
        max(date_day) as range_end
    from (
        select date_day from daily_spending
        union all
        select date_day from daily_productivity_agg
    ) as all_active_days
)

select
    dim_date.date_key,
    dim_date.date_day,
    coalesce(daily_spending.total_spending, 0) as total_spending,
    coalesce(daily_spending.transaction_count, 0) as transaction_count,
    coalesce(daily_productivity_agg.commit_count, 0) as commit_count,
    coalesce(daily_productivity_agg.pr_opened_count, 0) as pr_opened_count,
    coalesce(daily_productivity_agg.pr_merged_count, 0) as pr_merged_count
from dim_date
cross join active_range
left join daily_spending on dim_date.date_day = daily_spending.date_day
left join daily_productivity_agg on dim_date.date_day = daily_productivity_agg.date_day
where dim_date.date_day between active_range.range_start and active_range.range_end
order by dim_date.date_day
