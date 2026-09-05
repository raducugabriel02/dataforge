with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2024-01-01' as date)",
        end_date="cast('2028-01-01' as date)"
    ) }}
),

holidays as (
    select * from {{ ref('ro_legal_holidays') }}
)

select
    cast(spine.date_day as date) as date_day,
    {{ dbt_utils.generate_surrogate_key(['spine.date_day']) }} as date_key,
    extract(year from spine.date_day)::int as year,
    extract(quarter from spine.date_day)::int as quarter,
    extract(month from spine.date_day)::int as month,
    extract(isodow from spine.date_day)::int as iso_day_of_week,
    extract(week from spine.date_day)::int as iso_week,
    extract(isodow from spine.date_day) in (6, 7) as is_weekend,
    holidays.holiday_name is not null as is_legal_holiday_ro
from spine
left join holidays
    on extract(month from spine.date_day) = holidays.month
    and extract(day from spine.date_day) = holidays.day
