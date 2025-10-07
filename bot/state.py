"""Persistent runtime state management for the Telegram bot."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

STATE_EXPORT_FILE = Path("state.json")


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass
class GlobalTradeConfig:
    """Trading configuration shared across webhook triggered orders."""

    margin_usdt: float = 50.0
    lev_long: float = 10.0
    lev_short: float = 10.0
    isolated: bool = True
    hedge_mode: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "GlobalTradeConfig":
        if not isinstance(payload, Mapping):
            return cls()

        margin = _coerce_float(payload.get("margin_usdt") or payload.get("marginUsdt"), 50.0)
        lev_long = _coerce_float(payload.get("lev_long") or payload.get("levLong"), 10.0)
        lev_short = _coerce_float(payload.get("lev_short") or payload.get("levShort"), 10.0)
        isolated = _coerce_bool(payload.get("isolated"), True)
        hedge_mode = _coerce_bool(payload.get("hedge_mode") or payload.get("hedgeMode"), False)

        return cls(
            margin_usdt=margin,
            lev_long=lev_long,
            lev_short=lev_short,
            isolated=isolated,
            hedge_mode=hedge_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "margin_usdt": self.margin_usdt,
            "lev_long": self.lev_long,
            "lev_short": self.lev_short,
            "isolated": self.isolated,
            "hedge_mode": self.hedge_mode,
        }


@dataclass
class BotState:
    """Container for user configurable runtime options."""

    autotrade_enabled: bool = False
    autotrade_direction: str = "both"
    margin_mode: str = "cross"
    margin_asset: str | None = "USDT"
    leverage: float = 1.0
    max_trade_size: float | None = None
    daily_report_time: str | None = "21:00"
    last_symbol: str | None = None
    global_trade: GlobalTradeConfig = field(default_factory=GlobalTradeConfig)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BotState":
        """Create a :class:`BotState` from a mapping with sensible defaults."""

        data = dict(payload)
        margin_mode = str(data.get("margin_mode", data.get("marginMode", "cross")))
        leverage = _coerce_float(data.get("leverage", 1.0), 1.0)
        max_trade_raw = data.get("max_trade_size") or data.get("maxTradeSize")
        max_trade = _coerce_float(max_trade_raw, float("nan")) if max_trade_raw is not None else None
        if isinstance(max_trade, float) and (max_trade != max_trade):  # NaN check
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

        direction_raw = data.get("autotrade_direction") or data.get("autotradeDirection")
        if isinstance(direction_raw, str):
            direction_token = direction_raw.strip().lower()
        else:
            direction_token = ""

        if direction_token in {"long", "long_only", "longonly"}:
            autotrade_direction = "long"
        elif direction_token in {"short", "short_only", "shortonly"}:
            autotrade_direction = "short"
        else:
            autotrade_direction = "both"

        global_trade_payload = data.get("global_trade") or data.get("globalTrade")

        return cls(
            autotrade_enabled=bool(data.get("autotrade_enabled", data.get("autotradeEnabled", False))),
            autotrade_direction=autotrade_direction,
            margin_mode=margin_mode.lower(),
            margin_asset=margin_asset or "USDT",
            leverage=leverage,
            max_trade_size=max_trade,
            daily_report_time=daily_report_time,
            last_symbol=last_symbol or None,
            global_trade=GlobalTradeConfig.from_mapping(global_trade_payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation of the state."""

        payload = asdict(self)
        payload["margin_mode"] = self.margin_mode
        payload["autotrade_direction"] = self.normalised_autotrade_direction()
        if self.margin_asset:
            payload["margin_asset"] = self.margin_asset.upper()
        else:
            payload.pop("margin_asset", None)
        if self.last_symbol:
            payload["last_symbol"] = self.last_symbol.upper()
        else:
            payload.pop("last_symbol", None)
        payload["global_trade"] = self.global_trade.to_dict()
        return payload

    def normalised_autotrade_direction(self) -> str:
        """Return the configured autotrade direction token."""

        token = (self.autotrade_direction or "").strip().lower()
        if token in {"long", "short"}:
            return token
        return "both"

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


def export_state_snapshot(state: BotState, *, path: Path = STATE_EXPORT_FILE) -> None:
    """Write a condensed snapshot used by external services to *path*."""

    snapshot = {
        "autotrade_enabled": state.autotrade_enabled,
        "autotrade_direction": state.normalised_autotrade_direction(),
        "margin_mode": state.normalised_margin_mode(),
        "margin_coin": state.normalised_margin_asset(),
        "margin_asset": state.normalised_margin_asset(),
        "leverage": state.leverage,
        "max_trade_size": state.max_trade_size,
        "daily_report_time": state.daily_report_time,
        "last_symbol": state.last_symbol.upper() if state.last_symbol else None,
        "global_trade": state.global_trade.to_dict(),
    }

    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def load_state_snapshot(path: Path = STATE_EXPORT_FILE) -> dict[str, Any] | None:
    """Return the exported snapshot from *path* if available."""

    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if isinstance(payload, Mapping):
        return dict(payload)

    return None


__all__ = [
    "BotState",
    "GlobalTradeConfig",
    "DEFAULT_STATE",
    "STATE_EXPORT_FILE",
    "export_state_snapshot",
    "load_state_snapshot",
    "load_state",
    "save_state",
]
