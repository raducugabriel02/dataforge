with source as (
    select * from {{ source('raw', 'strava_activities') }}
),

renamed as (
    select
        activity_id,
        activity_date,
        name as activity_name,
        activity_type,
        elapsed_time_seconds,
        distance_meters,
        moving_time_seconds,
        average_heart_rate,
        max_heart_rate,
        calories,
        _loaded_at
    from source
)

select * from renamed
