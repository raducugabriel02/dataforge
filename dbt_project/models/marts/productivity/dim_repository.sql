-- Type-1 (latest-state) dimension, deliberately not SCD2: raw.github_repositories
-- already upserts to latest-known-state (see stg source docs), so any history
-- would have to come from a dbt snapshot taken BEFORE that overwrite — skipped
-- here because repo metadata history isn't analytically interesting for this
-- project, unlike dim_expense_category where "what category was this on the
-- transaction's date" genuinely matters.
with repositories as (
    select * from {{ ref('stg_github__repositories') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['repo_id']) }} as repo_key,
    repo_id,
    full_name,
    name,
    is_private,
    is_fork,
    language,
    created_at,
    pushed_at
from repositories
