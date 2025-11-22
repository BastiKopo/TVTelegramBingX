"""Helpers to enforce trading schedules."""
from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional, Sequence, Tuple

TimeWindow = Tuple[time, time]


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
) -> bool:
    """Return whether trading is allowed for ``now``.

    If ``windows`` is empty, the schedule is considered always open unless
    ``disable_weekends`` forbids the current day.
    """

    if disable_weekends and now.weekday() >= 5:
        return False

    if not windows:
        return True

    current_time = now.time()
    return any(_time_in_window(current_time, window) for window in windows)
