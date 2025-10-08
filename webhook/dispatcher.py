"""Utilities for dispatching webhook alerts to the Telegram bot."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from bot.state import BotState
from integrations.bingx_client import BingXClient, calc_order_qty

AlertPayload = Mapping[str, Any]

_ALERT_QUEUE: asyncio.Queue[AlertPayload] = asyncio.Queue()

#
# Trading context -----------------------------------------------------------
#
# These globals are configured by the Telegram bot when the webhook handling
# is initialised.  They are kept deliberately simple so that the dispatcher can
# be unit-tested in isolation by injecting lightweight fakes.
state: BotState = BotState()
client: BingXClient | None = None


def configure_trading_context(
    *, bot_state: BotState | None = None, bingx_client: BingXClient | None = None
) -> None:
    """Update the trading context used for auto-orders.

    Parameters may be omitted to keep the existing values which is convenient
    for tests patching only a subset of the dependencies.
    """

    global state, client

    if bot_state is not None:
        state = bot_state
    if bingx_client is not None:
        client = bingx_client


# ---------------------------------------------------------------------------
# Alert queue helpers
# ---------------------------------------------------------------------------
def get_alert_queue() -> asyncio.Queue[AlertPayload]:
    """Return the shared asyncio queue for TradingView alerts."""

    return _ALERT_QUEUE


async def publish_alert(alert: AlertPayload) -> None:
    """Add a validated alert to the shared queue."""

    await _ALERT_QUEUE.put(alert)


# ---------------------------------------------------------------------------
# Trading helpers
# ---------------------------------------------------------------------------
async def place_signal_order(symbol: str, side: str) -> Any:
    """Execute a market order for a TradingView signal.

    The order size is calculated based on the configured *margin_usdt* budget
    and leverage for the requested direction.  Margin mode and leverage are
    synchronised with BingX before submitting the order.  ``side`` must be one
    of ``"BUY"`` or ``"SELL"`` (case insensitive).
    """

    if client is None:
        raise RuntimeError("BingX client is not configured for order placement.")

    cfg = getattr(state, "global_trade", None)
    if cfg is None:
        raise RuntimeError("Global trade configuration missing on bot state.")

    side_token = side.strip().upper()
    if side_token not in {"BUY", "SELL"}:
        raise ValueError("Order side must be either 'BUY' or 'SELL'.")

    margin_mode = "ISOLATED" if getattr(cfg, "isolated", False) else "CROSSED"
    margin_coin = state.normalised_margin_asset()
    hedge_mode = bool(getattr(cfg, "hedge_mode", False))

    # 1) Configure position mode, margin mode and leverage on the exchange.
    await client.set_position_mode(hedge_mode)
    await client.set_margin_type(symbol=symbol, isolated=getattr(cfg, "isolated", False), margin_coin=margin_coin)

    lev_long = int(getattr(cfg, "lev_long", 1) or 1)
    lev_short = int(getattr(cfg, "lev_short", lev_long) or lev_long)
    leverage = lev_long if side_token == "BUY" else lev_short

    await client.set_leverage(
        symbol=symbol,
        lev_long=lev_long,
        lev_short=lev_short,
        hedge=hedge_mode,
        margin_coin=margin_coin,
    )

    # 2) Fetch latest price and exchange filters.
    price = await client.get_mark_price(symbol)
    filters = await client.get_symbol_filters(symbol)

    step_size = float(
        filters.get("step_size")
        or filters.get("stepSize")
        or filters.get("qty_step")
        or filters.get("qtyStep")
        or 0.0
    )
    min_qty = float(filters.get("min_qty") or filters.get("minQty") or 0.0)
    min_notional_raw = (
        filters.get("min_notional")
        or filters.get("minNotional")
        or filters.get("notional")
    )
    if step_size <= 0:
        raise RuntimeError("Exchange did not provide a valid quantity step size.")

    # 3) Calculate the order quantity respecting leverage and filters.
    margin_budget = float(getattr(cfg, "margin_usdt", 0.0) or 0.0)
    if margin_budget <= 0:
        raise RuntimeError("Margin budget missing from global trade configuration.")

    quantity = calc_order_qty(
        price=price,
        margin_usdt=margin_budget,
        leverage=leverage,
        step_size=step_size,
        min_qty=min_qty,
        min_notional=float(min_notional_raw) if min_notional_raw else None,
    )

    # 4) Submit the market order on BingX.
    order_kwargs: dict[str, Any] = {
        "symbol": symbol,
        "side": side_token,
        "quantity": quantity,
        "order_type": "MARKET",
        "reduce_only": False,
    }
    if hedge_mode:
        order_kwargs["position_side"] = "LONG" if side_token == "BUY" else "SHORT"

    return await client.place_order(**order_kwargs)


__all__ = [
    "AlertPayload",
    "client",
    "configure_trading_context",
    "get_alert_queue",
    "place_signal_order",
    "publish_alert",
    "state",
]
