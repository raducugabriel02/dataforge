-- Unlike raw.bank_transactions (immutable economic events with no natural
-- key, deduped via a content hash), GitHub gives genuine immutable natural
-- keys. Idempotency strategy is chosen per entity's real-world mutability:
--
--   * repositories and pull requests are MUTABLE (a PR moves open -> merged,
--     a repo's pushed_at keeps advancing) -> upsert on the natural key
--     (repo_id / pr_id), so raw always reflects the latest known state.
--   * commits are IMMUTABLE once created (a sha's message/author/date never
--     change) -> plain append-only insert, ON CONFLICT DO NOTHING on the
--     natural key (repo_full_name, sha).

CREATE TABLE IF NOT EXISTS raw.github_repositories (
    repo_id BIGINT PRIMARY KEY,
    full_name TEXT NOT NULL,
    name TEXT NOT NULL,
    is_private BOOLEAN NOT NULL,
    is_fork BOOLEAN NOT NULL,
    language TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    pushed_at TIMESTAMPTZ,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw.github_commits (
    repo_full_name TEXT NOT NULL,
    sha TEXT NOT NULL,
    author_login TEXT,
    author_name TEXT,
    committed_at TIMESTAMPTZ NOT NULL,
    message TEXT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_full_name, sha)
);

CREATE INDEX IF NOT EXISTS idx_github_commits_committed_at ON raw.github_commits (committed_at);

CREATE TABLE IF NOT EXISTS raw.github_pull_requests (
    pr_id BIGINT PRIMARY KEY,
    number INT NOT NULL,
    repo_full_name TEXT NOT NULL,
    state TEXT NOT NULL,
    title TEXT NOT NULL,
    author_login TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    merged_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_github_pull_requests_repo ON raw.github_pull_requests (repo_full_name);
