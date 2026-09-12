with source as (
    select * from {{ source('raw', 'github_commits') }}
),

renamed as (
    select
        repo_full_name,
        sha as commit_sha,
        author_login,
        author_name,
        committed_at,
        message,
        _loaded_at
    from source
)

select * from renamed
