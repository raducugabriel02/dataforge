with source as (
    select * from {{ source('raw', 'github_repositories') }}
),

renamed as (
    select
        repo_id,
        full_name,
        name,
        is_private,
        is_fork,
        language,
        created_at,
        pushed_at,
        _loaded_at
    from source
)

select * from renamed
