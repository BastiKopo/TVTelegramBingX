"""Utilities for dispatching webhook alerts to the Telegram bot."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from bot.state import BotState
from integrations.bingx_client import BingXClient
from services.trading import ExecutedOrder, execute_market_order

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
async def place_signal_order(
    symbol: str,
    side: str,
    *,
    quantity: float | None = None,
    margin_usdt: float | None = None,
    margin_mode: str | None = None,
    margin_coin: str | None = None,
    position_side: str | None = None,
    reduce_only: bool = False,
    client_order_id: str | None = None,
    state_override: BotState | None = None,
    client_override: BingXClient | None = None,
) -> ExecutedOrder:
    """Execute a market order for a TradingView signal.

    Delegates to :func:`services.trading.execute_market_order` so that manual
    and automated flows share identical synchronisation and sizing logic.
    """

    trading_client = client_override or client
    if trading_client is None:
        raise RuntimeError("BingX client is not configured for order placement.")

    trading_state = state_override or state
    if not isinstance(trading_state, BotState):
        raise RuntimeError("Trading state is not configured for order placement.")

    executed = await execute_market_order(
        trading_client,
        state=trading_state,
        symbol=symbol,
        side=side,
        quantity=quantity,
        margin_usdt=margin_usdt,
        margin_mode=margin_mode,
        margin_coin=margin_coin,
        position_side=position_side,
        reduce_only=reduce_only,
        client_order_id=client_order_id,
    )

    return executed


__all__ = [
    "AlertPayload",
    "client",
    "configure_trading_context",
    "get_alert_queue",
    "place_signal_order",
    "publish_alert",
    "state",
]
