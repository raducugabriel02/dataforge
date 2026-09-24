-- Grain: one row per Strava activity — atomic fact, same level as
-- fact_financial_transactions. activity_type stays a plain inline column
-- (not a separate dimension table) for the same reason `currency` was added
-- inline to fact_financial_transactions rather than as its own dim: a small,
-- stable set of categorical values naturally scoped to this one fact, not a
-- conformed dimension shared across other facts.
--
-- Deliberately NOT incremental (unlike fact_financial_transactions): raw.strava_activities
-- is upsert (mutable entity, see source docs) and export volume is tiny at
-- this project's personal scale — a full rebuild every run is negligible
-- cost and, unlike an anti-join filter, naturally picks up renamed/re-typed
-- activities from a later export with no extra logic.
with activities as (
    select * from {{ ref('stg_strava__activities') }}
),

dim_date as (
    select * from {{ ref('dim_date') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['activities.activity_id']) }} as activity_key,
    activities.activity_id,
    dim_date.date_key,
    activities.activity_date,
    activities.activity_name,
    activities.activity_type,
    activities.elapsed_time_seconds,
    activities.distance_meters,
    activities.moving_time_seconds,
    activities.average_heart_rate,
    activities.max_heart_rate,
    activities.calories
from activities
join dim_date
    on cast(activities.activity_date as date) = dim_date.date_day
