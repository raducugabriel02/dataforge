"""Parser for Strava's bulk account-export `activities.csv`.

Strava's export template concatenates several internal per-sport templates,
so the header repeats some column names (Elapsed Time, Distance, Max Heart
Rate, Relative Effort, Commute each appear twice at different positions with
different meaning/precision). `csv.DictReader` builds each row via
`dict(zip(fieldnames, row))`, so a duplicate column name silently overwrites
the earlier one — reading by name would lose the first "Elapsed Time"/
"Distance" values without any error. We read positionally instead, against a
header whose exact shape (order + duplicates) is validated up front.
"""

from __future__ import annotations

import csv
import decimal
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ingestion.strava.models import ParseResult, RawActivity, RowParseError

_ROW_ERROR_TYPES = (ValueError, IndexError, decimal.InvalidOperation, ValidationError)

# Column positions used out of Strava's 103-column export header (see
# EXPECTED_HEADER below for the full, real, header this was captured from).
_IDX_ACTIVITY_ID = 0
_IDX_ACTIVITY_DATE = 1
_IDX_NAME = 2
_IDX_ACTIVITY_TYPE = 3
_IDX_ELAPSED_TIME = 5  # generic summary field, populated for every activity type
_IDX_DISTANCE = 6  # generic summary field, kilometers (verified against real
# export: detailed block's meter-denominated Distance at idx 17, cross-checked
# via elapsed_time * average_speed, confirms idx 6 is km, not meters as first
# assumed before any real export existed)
_KM_TO_METERS = decimal.Decimal(1000)
_IDX_MAX_HEART_RATE = 7
_IDX_MOVING_TIME = 16  # not duplicated; only meaningful for GPS-tracked activities
_IDX_AVERAGE_HEART_RATE = 31
_IDX_CALORIES = 34

_DATE_FORMAT = "%b %d, %Y, %I:%M:%S %p"

EXPECTED_HEADER: tuple[str, ...] = (
    "Activity ID", "Activity Date", "Activity Name", "Activity Type",
    "Activity Description", "Elapsed Time", "Distance", "Max Heart Rate",
    "Relative Effort", "Commute", "Activity Private Note", "Activity Gear",
    "Filename", "Athlete Weight", "Bike Weight", "Elapsed Time", "Moving Time",
    "Distance", "Max Speed", "Average Speed", "Elevation Gain",
    "Elevation Loss", "Elevation Low", "Elevation High", "Max Grade",
    "Average Grade", "Average Positive Grade", "Average Negative Grade",
    "Max Cadence", "Average Cadence", "Max Heart Rate", "Average Heart Rate",
    "Max Watts", "Average Watts", "Calories", "Max Temperature",
    "Average Temperature", "Relative Effort", "Total Work", "Number of Runs",
    "Uphill Time", "Downhill Time", "Other Time", "Perceived Exertion",
    "Type", "Start Time", "Weighted Average Power", "Power Count",
    "Prefer Perceived Exertion", "Perceived Relative Effort", "Commute",
    "Total Weight Lifted", "From Upload", "Grade Adjusted Distance",
    "Weather Observation Time", "Weather Condition", "Weather Temperature",
    "Apparent Temperature", "Dewpoint", "Humidity", "Weather Pressure",
    "Wind Speed", "Wind Gust", "Wind Bearing", "Precipitation Intensity",
    "Sunrise Time", "Sunset Time", "Moon Phase", "Bike", "Gear",
    "Precipitation Probability", "Precipitation Type", "Cloud Cover",
    "Weather Visibility", "UV Index", "Weather Ozone", "Jump Count",
    "Total Grit", "Average Flow", "Flagged", "Average Elapsed Speed",
    "Dirt Distance", "Newly Explored Distance", "Newly Explored Dirt Distance",
    "Activity Count", "Total Steps", "Carbon Saved", "Pool Length",
    "Training Load", "Intensity", "Average Grade Adjusted Pace", "Timer Time",
    "Total Cycles", "Recovery", "With Pet", "Competition", "Long Run",
    "For a Cause", "With Kid", "Downhill Distance", "Total Sets",
    "Total Reps", "Media",
)


class StravaSchemaDriftError(Exception):
    """Raised when the export header no longer matches the validated shape.

    A silent drift (column added/removed/reordered) would misalign every
    positional index above — the whole file is rejected rather than guessing.
    """

    def __init__(self, expected: Sequence[str], actual: Sequence[str]) -> None:
        super().__init__(
            f"Unexpected Strava export header (expected {len(expected)} columns, "
            f"got {len(actual)}). Strava likely changed its export format — "
            "update the column positions in ingestion/strava/parser.py before re-ingesting."
        )
        self.expected = list(expected)
        self.actual = list(actual)


def _opt(text: str) -> str | None:
    text = text.strip()
    return text or None


def _parse_seconds(text: str) -> int:
    # Strava formats duration fields inconsistently across columns in the same
    # row (e.g. real export: Elapsed Time "66" but Moving Time "66.0") — parse
    # via float first so either shape works, instead of a bare int() that
    # crashes on the ".0" form.
    return int(float(text))


class StravaActivityParser:
    def parse(self, path: Path) -> ParseResult:
        result = ParseResult()
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            self._validate_header(header)
            for line_number, row in enumerate(reader, start=2):
                try:
                    result.activities.append(self._parse_row(row, line_number))
                except _ROW_ERROR_TYPES as exc:
                    result.errors.append(RowParseError(line_number, row, str(exc)))
        return result

    def _validate_header(self, header: Sequence[str] | None) -> None:
        if header is None or list(header) != list(EXPECTED_HEADER):
            raise StravaSchemaDriftError(EXPECTED_HEADER, header or [])

    def _parse_row(self, row: list[str], line_number: int) -> RawActivity:
        moving_time = _opt(row[_IDX_MOVING_TIME])
        avg_hr = _opt(row[_IDX_AVERAGE_HEART_RATE])
        max_hr = _opt(row[_IDX_MAX_HEART_RATE])
        calories = _opt(row[_IDX_CALORIES])
        return RawActivity(
            activity_id=int(row[_IDX_ACTIVITY_ID]),
            activity_date=datetime.strptime(row[_IDX_ACTIVITY_DATE].strip(), _DATE_FORMAT),
            name=row[_IDX_NAME],
            activity_type=row[_IDX_ACTIVITY_TYPE],
            elapsed_time_seconds=_parse_seconds(row[_IDX_ELAPSED_TIME]),
            distance_meters=decimal.Decimal(row[_IDX_DISTANCE]) * _KM_TO_METERS,
            moving_time_seconds=_parse_seconds(moving_time) if moving_time else None,
            average_heart_rate=decimal.Decimal(avg_hr) if avg_hr else None,
            max_heart_rate=decimal.Decimal(max_hr) if max_hr else None,
            calories=decimal.Decimal(calories) if calories else None,
        )
