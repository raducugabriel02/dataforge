from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion.strava.parser import EXPECTED_HEADER, StravaActivityParser, StravaSchemaDriftError

_NUM_COLUMNS = len(EXPECTED_HEADER)


def _row(overrides: dict[int, str]) -> list[str]:
    values = [""] * _NUM_COLUMNS
    for index, value in overrides.items():
        values[index] = value
    return values


def _write_csv(path: Path, rows: list[list[str]]) -> Path:
    # newline="" avoids Path.write_text's universal-newline translation
    # double-encoding the \r\n the csv module already writes (which would
    # otherwise produce a spurious blank row after every real one on Windows).
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(EXPECTED_HEADER)
        writer.writerows(rows)
    return path


# Columns exercised in the fixtures below, matching ingestion/strava/parser.py's
# positional indices into Strava's real (duplicate-header) export.
_ACTIVITY_ID, _ACTIVITY_DATE, _NAME, _ACTIVITY_TYPE = 0, 1, 2, 3
_ELAPSED_TIME, _DISTANCE, _MAX_HR = 5, 6, 7
_MOVING_TIME = 16
_AVG_HR = 31
_CALORIES = 34


def test_parses_walk_and_run_with_only_basic_fields_populated(tmp_path: Path) -> None:
    # Mirrors what a watch-synced activity (no power meter/weather sensors)
    # actually populates: the generic summary columns, not the detailed block.
    walk = _row(
        {
            _ACTIVITY_ID: "12345678901",
            _ACTIVITY_DATE: "Sep 16, 2026, 6:32:10 PM",
            _NAME: "Afternoon Walk",
            _ACTIVITY_TYPE: "Walk",
            _ELAPSED_TIME: "1200",
            _DISTANCE: "1.5005",
        }
    )
    run = _row(
        {
            _ACTIVITY_ID: "12345678902",
            _ACTIVITY_DATE: "Sep 16, 2026, 7:05:00 PM",
            _NAME: "Indoor Run",
            _ACTIVITY_TYPE: "Run",
            _ELAPSED_TIME: "1800",
            _DISTANCE: "3",
            _MOVING_TIME: "1750",
            _MAX_HR: "168",
            _AVG_HR: "145.5",
            _CALORIES: "320",
        }
    )
    path = _write_csv(tmp_path / "activities.csv", [walk, run])

    result = StravaActivityParser().parse(path)

    assert result.errors == []
    assert len(result.activities) == 2

    first = result.activities[0]
    assert first.activity_id == 12345678901
    assert first.activity_date == datetime(2026, 9, 16, 18, 32, 10)
    assert first.activity_type == "Walk"
    assert first.elapsed_time_seconds == 1200
    assert first.distance_meters == Decimal("1500.5")
    assert first.moving_time_seconds is None
    assert first.average_heart_rate is None
    assert first.calories is None

    second = result.activities[1]
    assert second.activity_type == "Run"
    assert second.moving_time_seconds == 1750
    assert second.max_heart_rate == Decimal("168")
    assert second.average_heart_rate == Decimal("145.5")
    assert second.calories == Decimal("320")


def test_parses_float_formatted_duration_fields(tmp_path: Path) -> None:
    # Real Strava export gotcha: Moving Time is written as "66.0", not "66",
    # while Elapsed Time in the same row is plain "66" — inconsistent within
    # a single row, a bare int() on Moving Time crashes on the real file.
    row = _row(
        {
            _ACTIVITY_ID: "20201332451",
            _ACTIVITY_DATE: "Sep 16, 2026, 3:31:54 PM",
            _NAME: "Alergare in interior",
            _ACTIVITY_TYPE: "Run",
            _ELAPSED_TIME: "66",
            _DISTANCE: "0.15",
            _MOVING_TIME: "66.0",
        }
    )
    path = _write_csv(tmp_path / "activities.csv", [row])

    result = StravaActivityParser().parse(path)

    assert result.errors == []
    activity = result.activities[0]
    assert activity.elapsed_time_seconds == 66
    assert activity.moving_time_seconds == 66
    assert activity.distance_meters == Decimal("150.0")


def test_skips_corrupt_rows_but_keeps_valid_ones(tmp_path: Path) -> None:
    good = _row(
        {
            _ACTIVITY_ID: "111",
            _ACTIVITY_DATE: "Sep 16, 2026, 6:32:10 PM",
            _NAME: "Walk",
            _ACTIVITY_TYPE: "Walk",
            _ELAPSED_TIME: "600",
            _DISTANCE: "800",
        }
    )
    corrupt = _row(
        {
            _ACTIVITY_ID: "NOT_AN_ID",
            _ACTIVITY_DATE: "Sep 16, 2026, 6:32:10 PM",
            _NAME: "Broken",
            _ACTIVITY_TYPE: "Walk",
            _ELAPSED_TIME: "600",
            _DISTANCE: "800",
        }
    )
    path = _write_csv(tmp_path / "activities.csv", [good, corrupt])

    result = StravaActivityParser().parse(path)

    assert len(result.activities) == 1
    assert len(result.errors) == 1
    assert result.errors[0].line_number == 3


def test_raises_on_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "activities.csv"
    path.write_text("Activity ID,Activity Date,Activity Name\n1,x,y\n", encoding="utf-8")

    with pytest.raises(StravaSchemaDriftError):
        StravaActivityParser().parse(path)
