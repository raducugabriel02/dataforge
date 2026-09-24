-- Grain: one row per calendar day that had at least one activity — sparse,
-- same pattern as fact_daily_productivity (not a dense spine; the combined
-- mart is where sparse per-source facts get coalesced onto a dense date
-- spine). date_key is the tested unique key (see schema.yml) since this is
-- a day-level aggregate, not a natural-key entity.
with activities as (
    select * from {{ ref('fact_activities') }}
)

select
    date_key,
    count(*) as activity_count,
    sum(distance_meters) as total_distance_meters,
    sum(elapsed_time_seconds) as total_elapsed_time_seconds,
    sum(coalesce(calories, 0)) as total_calories
from activities
group by 1
