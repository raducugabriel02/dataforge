from __future__ import annotations

import psycopg
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingestion.config import PostgresConfig
from ingestion.strava.models import RawActivity

# activity_id is a mutable-entity natural key -> upsert keeps raw at the
# latest known state (see infra/postgres/init/04_create_strava_raw_tables.sql).
_UPSERT_ACTIVITY_SQL = """
    INSERT INTO raw.strava_activities
        (activity_id, activity_date, name, activity_type, elapsed_time_seconds,
         distance_meters, moving_time_seconds, average_heart_rate, max_heart_rate, calories)
    VALUES
        (%(activity_id)s, %(activity_date)s, %(name)s, %(activity_type)s,
         %(elapsed_time_seconds)s, %(distance_meters)s, %(moving_time_seconds)s,
         %(average_heart_rate)s, %(max_heart_rate)s, %(calories)s)
    ON CONFLICT (activity_id) DO UPDATE SET
        activity_date = EXCLUDED.activity_date,
        name = EXCLUDED.name,
        activity_type = EXCLUDED.activity_type,
        elapsed_time_seconds = EXCLUDED.elapsed_time_seconds,
        distance_meters = EXCLUDED.distance_meters,
        moving_time_seconds = EXCLUDED.moving_time_seconds,
        average_heart_rate = EXCLUDED.average_heart_rate,
        max_heart_rate = EXCLUDED.max_heart_rate,
        calories = EXCLUDED.calories,
        _loaded_at = now()
"""

_RETRY_ON_TRANSIENT_DB_ERROR = retry(
    retry=retry_if_exception_type(psycopg.OperationalError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


class StravaRawLoader:
    def __init__(self, config: PostgresConfig) -> None:
        self._config = config

    @_RETRY_ON_TRANSIENT_DB_ERROR
    def load(self, activities: list[RawActivity]) -> int:
        with psycopg.connect(self._config.dsn) as conn, conn.cursor() as cur:
            for activity in activities:
                cur.execute(_UPSERT_ACTIVITY_SQL, activity.model_dump())
            conn.commit()
        logger.bind(rows_upserted=len(activities)).info("strava_activities_load_complete")
        return len(activities)
