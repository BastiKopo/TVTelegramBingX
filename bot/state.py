"""Persistent runtime state management for the Telegram bot."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class BotState:
    """Container for user configurable runtime options."""

    autotrade_enabled: bool = False
    margin_mode: str = "cross"
    leverage: float = 1.0
    max_trade_size: float | None = None
    daily_report_time: str | None = "21:00"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BotState":
        """Create a :class:`BotState` from a mapping with sensible defaults."""

        data = dict(payload)
        margin_mode = str(data.get("margin_mode", data.get("marginMode", "cross")))
        leverage_raw = data.get("leverage", 1.0)
        try:
            leverage = float(leverage_raw)
        except (TypeError, ValueError):
            leverage = 1.0
        max_trade_raw = data.get("max_trade_size") or data.get("maxTradeSize")
        try:
            max_trade = float(max_trade_raw) if max_trade_raw is not None else None
        except (TypeError, ValueError):
            max_trade = None
        daily_report_time = data.get("daily_report_time") or data.get("dailyReportTime")
        if isinstance(daily_report_time, str):
            daily_report_time = daily_report_time.strip() or None
        else:
            daily_report_time = None

        return cls(
            autotrade_enabled=bool(data.get("autotrade_enabled", data.get("autotradeEnabled", False))),
            margin_mode=margin_mode.lower(),
            leverage=leverage,
            max_trade_size=max_trade,
            daily_report_time=daily_report_time,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation of the state."""

        payload = asdict(self)
        payload["margin_mode"] = self.margin_mode
        return payload

    def normalised_margin_mode(self) -> str:
        """Return the margin mode in BingX friendly formatting."""

        mode = self.margin_mode.strip().lower()
        if mode in {"cross", "crossed"}:
            return "CROSSED"
        if mode in {"isolated", "isol"}:
            return "ISOLATED"
        return mode.upper() or "CROSSED"


DEFAULT_STATE = BotState()


def load_state(path: Path) -> BotState:
    """Load the bot state from *path*. Return :data:`DEFAULT_STATE` on failure."""

    if not path.exists():
        return DEFAULT_STATE

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_STATE

    if isinstance(payload, Mapping):
        return BotState.from_mapping(payload)

    return DEFAULT_STATE


def save_state(path: Path, state: BotState) -> None:
    """Persist *state* to *path* atomically."""

    path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


__all__ = ["BotState", "DEFAULT_STATE", "load_state", "save_state"]
