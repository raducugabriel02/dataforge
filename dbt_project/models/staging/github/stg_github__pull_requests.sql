with source as (
    select * from {{ source('raw', 'github_pull_requests') }}
),

renamed as (
    select
        pr_id,
        number as pr_number,
        repo_full_name,
        state,
        title,
        author_login,
        created_at,
        merged_at,
        closed_at,
        _loaded_at
    from source
)

select * from renamed
