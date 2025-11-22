from datetime import datetime, time

import pytest

from tvtelegrambingx.utils.schedule import is_within_schedule, parse_time_windows


def test_parse_time_windows_supports_multiple_ranges():
    windows = parse_time_windows("08:00-12:00, 13:30-18:00")
    assert windows == [
        (time(hour=8), time(hour=12)),
        (time(hour=13, minute=30), time(hour=18)),
    ]


def test_parse_time_windows_errors_on_invalid_input():
    with pytest.raises(ValueError):
        parse_time_windows("invalid")


def test_is_within_schedule_with_weekends_disabled():
    windows = parse_time_windows("09:00-17:00")
    saturday = datetime(year=2024, month=6, day=1, hour=10)
    assert not is_within_schedule(saturday, windows, disable_weekends=True)


def test_is_within_schedule_respects_windows_and_midnight_wrap():
    windows = parse_time_windows("22:00-02:00")
    evening = datetime(year=2024, month=5, day=31, hour=23)
    morning = datetime(year=2024, month=6, day=1, hour=1)
    outside = datetime(year=2024, month=5, day=31, hour=15)

    assert is_within_schedule(evening, windows)
    assert is_within_schedule(morning, windows)
    assert not is_within_schedule(outside, windows)
