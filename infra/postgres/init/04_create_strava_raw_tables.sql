-- activity_id is a MUTABLE natural key (a user can rename or re-type an
-- activity on Strava between exports, e.g. mis-tagged "Run" fixed to "Walk")
-- -> upsert, same idempotency strategy as raw.github_repositories /
-- raw.github_pull_requests, not the append-only pattern used for commits.

CREATE TABLE IF NOT EXISTS raw.strava_activities (
    activity_id BIGINT PRIMARY KEY,
    activity_date TIMESTAMP NOT NULL,
    name TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    elapsed_time_seconds INT NOT NULL,
    distance_meters NUMERIC(10, 2) NOT NULL,
    moving_time_seconds INT,
    average_heart_rate NUMERIC(5, 2),
    max_heart_rate NUMERIC(5, 2),
    calories NUMERIC(8, 2),
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strava_activities_date ON raw.strava_activities (activity_date);
