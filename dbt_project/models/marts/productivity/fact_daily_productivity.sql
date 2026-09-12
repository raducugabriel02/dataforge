-- Grain: one row per (repository, calendar day) that had at least one commit
-- or pull-request event — sparse like fact_financial_transactions, not a
-- dense day-by-day spine. No single natural id exists for an aggregate row
-- like this, so the grain itself (repo_key, date_key) is the tested key
-- (see schema.yml's unique_combination_of_columns) instead of inventing one.
with commits as (
    select * from {{ ref('stg_github__commits') }}
),

pull_requests as (
    select * from {{ ref('stg_github__pull_requests') }}
),

dim_repository as (
    select * from {{ ref('dim_repository') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
),

commits_daily as (
    select
        repo_full_name,
        cast(committed_at as date) as activity_date,
        count(*) as commit_count
    from commits
    group by 1, 2
),

prs_opened_daily as (
    select
        repo_full_name,
        cast(created_at as date) as activity_date,
        count(*) as pr_opened_count
    from pull_requests
    group by 1, 2
),

prs_merged_daily as (
    select
        repo_full_name,
        cast(merged_at as date) as activity_date,
        count(*) as pr_merged_count
    from pull_requests
    where merged_at is not null
    group by 1, 2
),

daily_activity as (
    select repo_full_name, activity_date from commits_daily
    union
    select repo_full_name, activity_date from prs_opened_daily
    union
    select repo_full_name, activity_date from prs_merged_daily
)

select
    dim_repository.repo_key,
    dim_date.date_key,
    coalesce(commits_daily.commit_count, 0) as commit_count,
    coalesce(prs_opened_daily.pr_opened_count, 0) as pr_opened_count,
    coalesce(prs_merged_daily.pr_merged_count, 0) as pr_merged_count
from daily_activity
join dim_repository
    on daily_activity.repo_full_name = dim_repository.full_name
join dim_date
    on daily_activity.activity_date = dim_date.date_day
left join commits_daily
    on daily_activity.repo_full_name = commits_daily.repo_full_name
    and daily_activity.activity_date = commits_daily.activity_date
left join prs_opened_daily
    on daily_activity.repo_full_name = prs_opened_daily.repo_full_name
    and daily_activity.activity_date = prs_opened_daily.activity_date
left join prs_merged_daily
    on daily_activity.repo_full_name = prs_merged_daily.repo_full_name
    and daily_activity.activity_date = prs_merged_daily.activity_date
