"""Helpers to expose Telegram-configured trading preferences.

The module provides a minimal abstraction so other components can treat the
Telegram UI as the canonical source for margin and leverage settings.  The
preferences ultimately live in :class:`bot.state.BotState` which mirrors the
options stored in ``bot_state.json``/``state.json``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from bot.state import BotState, GlobalTradeConfig

__all__ = ["get_prefs"]


def _extract_trade_config(state: BotState | None) -> GlobalTradeConfig:
    """Return a ``GlobalTradeConfig`` instance from ``state``.

    When *state* is ``None`` a default configuration with neutral values is
    returned so callers do not have to guard against missing state
    initialisation.
    """

    if isinstance(state, BotState):
        return state.global_trade
    return GlobalTradeConfig()


def get_prefs(
    chat_id: int | str | None,
    symbol: str,
    *,
    state: BotState | None = None,
) -> dict[str, Any]:
    """Return the persisted Telegram preferences for *symbol*.

    Parameters
    ----------
    chat_id:
        Identifier of the Telegram chat requesting the trade.  It is currently
        unused but part of the signature so the helper can evolve to
        multi-chat setups without touching the call sites again.
    symbol:
        Normalised trading symbol (``AAA-BBB``).  The argument is accepted for
        future extensibility; at present preferences do not differ by symbol
        because BingX uses a single margin/leverage configuration across all
        instruments.
    state:
        Optional :class:`BotState` providing the latest Telegram configuration
        values.
    """

    cfg = _extract_trade_config(state)
    payload = asdict(cfg)

    margin_usdt = float(payload.get("margin_usdt", 0.0) or 0.0)
    lev_long = int(payload.get("lev_long", 0) or 0)
    lev_short = int(payload.get("lev_short", lev_long) or lev_long)

    result: dict[str, Any] = {
        "margin_usdt": margin_usdt,
        "lev_long": lev_long,
        "lev_short": lev_short,
    }

    if lev_long == lev_short and lev_long > 0:
        result["leverage"] = lev_long

    return result
