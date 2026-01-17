"""Helpers to enforce trading schedules."""
from __future__ import annotations

from datetime import datetime, time
from typing import Iterable, List, Optional, Sequence, Set, Tuple

TimeWindow = Tuple[time, time]
WeekdaySet = Set[int]


def _parse_time(value: str) -> time:
    try:
        hours, minutes = value.split(":", 1)
        return time(hour=int(hours), minute=int(minutes))
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Ungültige Zeitangabe: {value}") from exc


def parse_time_windows(raw_value: Optional[str]) -> List[TimeWindow]:
    """Parse a comma-separated list of ``HH:MM-HH:MM`` windows.

    Empty input results in an empty list which is treated as "always on" by
    :func:`is_within_schedule`.
    """

    if raw_value in {None, ""}:
        return []

    windows: List[TimeWindow] = []
    for part in raw_value.split(','):
        trimmed = part.strip()
        if not trimmed:
            continue
        if "-" not in trimmed:
            raise ValueError(
                "Ungültiges Zeitfenster. Erwartetes Format: HH:MM-HH:MM (kommagetrennt)."
            )
        start_raw, end_raw = trimmed.split("-", 1)
        start = _parse_time(start_raw.strip())
        end = _parse_time(end_raw.strip())
        windows.append((start, end))

    return windows


def parse_active_days(raw_value: Optional[str]) -> WeekdaySet:
    """Parse a comma-separated list of active weekdays.

    Supported values: mon..sun, mo..so, or full German/English names.
    Empty input results in an empty set which means "all days".
    """

    if raw_value in {None, ""}:
        return set()

    normalized_map = {
        "mon": 0,
        "monday": 0,
        "mo": 0,
        "montag": 0,
        "tue": 1,
        "tues": 1,
        "tuesday": 1,
        "di": 1,
        "dienstag": 1,
        "wed": 2,
        "weds": 2,
        "wednesday": 2,
        "mi": 2,
        "mittwoch": 2,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "thursday": 3,
        "do": 3,
        "donnerstag": 3,
        "fri": 4,
        "friday": 4,
        "fr": 4,
        "freitag": 4,
        "sat": 5,
        "saturday": 5,
        "sa": 5,
        "samstag": 5,
        "sun": 6,
        "sunday": 6,
        "so": 6,
        "sonntag": 6,
    }

    days: WeekdaySet = set()
    for part in raw_value.split(","):
        token = part.strip().lower()
        if not token:
            continue
        if "-" in token:
            start_raw, end_raw = [item.strip() for item in token.split("-", 1)]
            if start_raw not in normalized_map or end_raw not in normalized_map:
                raise ValueError(
                    "Ungültiger Wochentag im Bereich. Beispiel: mon-fri oder mo-fr."
                )
            start = normalized_map[start_raw]
            end = normalized_map[end_raw]
            if start <= end:
                days.update(range(start, end + 1))
            else:
                days.update(range(start, 7))
                days.update(range(0, end + 1))
            continue
        if token not in normalized_map:
            raise ValueError(
                "Ungültiger Wochentag. Erlaubt: mon..sun, mo..so, montag..sonntag."
            )
        days.add(normalized_map[token])

    return days


def _time_in_window(current: time, window: TimeWindow) -> bool:
    start, end = window
    if start <= end:
        return start <= current < end
    # Window across midnight: 22:00-02:00
    return current >= start or current < end


def is_within_schedule(
    now: datetime,
    windows: Sequence[TimeWindow],
    disable_weekends: bool = False,
    active_days: Optional[Iterable[int]] = None,
) -> bool:
    """Return whether trading is allowed for ``now``.

    If ``windows`` is empty, the schedule is considered always open unless
    ``disable_weekends`` forbids the current day.
    """

    if disable_weekends and now.weekday() >= 5:
        return False

    if active_days:
        day_set = set(active_days)
        if now.weekday() not in day_set:
            return False

    if not windows:
        return True

    current_time = now.time()
    return any(_time_in_window(current_time, window) for window in windows)
