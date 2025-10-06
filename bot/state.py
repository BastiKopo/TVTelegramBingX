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
    margin_asset: str | None = "USDT"
    leverage: float = 1.0
    max_trade_size: float | None = None
    daily_report_time: str | None = "21:00"
    last_symbol: str | None = None

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

        last_symbol_raw = data.get("last_symbol") or data.get("lastSymbol")
        if last_symbol_raw:
            text = str(last_symbol_raw).strip()
            if ":" in text:
                text = text.rsplit(":", 1)[-1]
            last_symbol = text.upper() or None
        else:
            last_symbol = None

        margin_asset_raw = data.get("margin_asset") or data.get("marginAsset")
        if isinstance(margin_asset_raw, str):
            margin_asset = margin_asset_raw.strip().upper() or None
        else:
            margin_asset = None

        return cls(
            autotrade_enabled=bool(data.get("autotrade_enabled", data.get("autotradeEnabled", False))),
            margin_mode=margin_mode.lower(),
            margin_asset=margin_asset or "USDT",
            leverage=leverage,
            max_trade_size=max_trade,
            daily_report_time=daily_report_time,
            last_symbol=last_symbol or None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation of the state."""

        payload = asdict(self)
        payload["margin_mode"] = self.margin_mode
        if self.margin_asset:
            payload["margin_asset"] = self.margin_asset.upper()
        else:
            payload.pop("margin_asset", None)
        if self.last_symbol:
            payload["last_symbol"] = self.last_symbol.upper()
        else:
            payload.pop("last_symbol", None)
        return payload

    def normalised_margin_mode(self) -> str:
        """Return the margin mode in BingX friendly formatting."""

        mode = self.margin_mode.strip().lower()
        if mode in {"cross", "crossed"}:
            return "CROSSED"
        if mode in {"isolated", "isol"}:
            return "ISOLATED"
        return mode.upper() or "CROSSED"

    def normalised_margin_asset(self) -> str:
        """Return the configured margin asset in uppercase."""

        asset = (self.margin_asset or "").strip().upper()
        if not asset:
            return "USDT"
        return asset


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
