"""Offline smoke test for manual and auto trade execution paths.

Run with ``python scripts/trading_flow_smoke_test.py`` to verify that both
manual and automated order helpers can prepare a payload and pass it to the
shared BingX client wrapper. The script uses an in-memory fake client so that
no real network calls are performed.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from types import SimpleNamespace

if 'telegram' not in sys.modules:
    class _DummyInlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, **kwargs: object) -> None:
            self.text = text
            self.callback_data = callback_data
            self.kwargs = kwargs

    class _DummyInlineKeyboardMarkup:
        def __init__(self, inline_keyboard) -> None:
            self.inline_keyboard = inline_keyboard

    class _DummyBotCommand:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyReplyKeyboardMarkup:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyUpdate:
        message = None

    sys.modules['telegram'] = SimpleNamespace(
        InlineKeyboardButton=_DummyInlineKeyboardButton,
        InlineKeyboardMarkup=_DummyInlineKeyboardMarkup,
        BotCommand=_DummyBotCommand,
        ReplyKeyboardMarkup=_DummyReplyKeyboardMarkup,
        Update=_DummyUpdate,
    )

if 'telegram.ext' not in sys.modules:
    class _DummyApplication:
        def __init__(self) -> None:
            self.bot_data = {}
            self.bot = SimpleNamespace(
                set_my_commands=lambda *args, **kwargs: None,
                send_message=lambda *args, **kwargs: None,
            )
            self.job_queue = None

        def add_handler(self, handler) -> None:
            self.bot_data.setdefault('handlers', []).append(handler)

    class _DummyApplicationBuilder:
        def __init__(self) -> None:
            self._token = None

        def token(self, value: str) -> '_DummyApplicationBuilder':
            self._token = value
            return self

        def build(self) -> _DummyApplication:
            return _DummyApplication()

    class _DummyCommandHandler:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyCallbackQueryHandler:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyContextTypes:
        DEFAULT_TYPE = object()

    sys.modules['telegram.ext'] = SimpleNamespace(
        Application=_DummyApplication,
        ApplicationBuilder=_DummyApplicationBuilder,
        CommandHandler=_DummyCommandHandler,
        CallbackQueryHandler=_DummyCallbackQueryHandler,
        ContextTypes=_DummyContextTypes,
    )

import asyncio
from dataclasses import dataclass, field
from typing import Any, Mapping

from bot.state import BotState, GlobalTradeConfig
from bot.telegram_bot import _prepare_autotrade_order
from services.trading import ExecutedOrder, execute_market_order


@dataclass
class FakeBingXClient:
    """Minimal in-memory stub that mimics :class:`BingXClient` behaviour."""

    mark_price: float = 30_000.0
    filters: Mapping[str, float] = field(
        default_factory=lambda: {"step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}
    )
    order_calls: list[Mapping[str, Any]] = field(default_factory=list)

    async def set_position_mode(self, hedge_mode: bool) -> None:
        self.order_calls.append({"action": "set_position_mode", "hedge_mode": hedge_mode})

    async def set_margin_type(self, *, symbol: str, margin_mode: str, margin_coin: str) -> None:
        self.order_calls.append(
            {
                "action": "set_margin_type",
                "symbol": symbol,
                "margin_mode": margin_mode,
                "margin_coin": margin_coin,
            }
        )

    async def set_leverage(
        self,
        *,
        symbol: str,
        lev_long: int,
        lev_short: int,
        hedge: bool,
        margin_coin: str,
    ) -> None:
        self.order_calls.append(
            {
                "action": "set_leverage",
                "symbol": symbol,
                "lev_long": lev_long,
                "lev_short": lev_short,
                "hedge": hedge,
                "margin_coin": margin_coin,
            }
        )

    async def get_mark_price(self, symbol: str) -> float:
        self.order_calls.append({"action": "get_mark_price", "symbol": symbol})
        return self.mark_price

    async def get_symbol_filters(self, symbol: str) -> Mapping[str, float]:
        self.order_calls.append({"action": "get_symbol_filters", "symbol": symbol})
        return self.filters

    async def place_futures_market_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool,
        position_side: str | None,
        client_order_id: str | None,
    ) -> Mapping[str, Any]:
        payload = {
            "action": "place_futures_market_order",
            "symbol": symbol,
            "side": side,
            "quantity": qty,
            "reduce_only": reduce_only,
            "position_side": position_side,
            "client_order_id": client_order_id,
        }
        self.order_calls.append(payload)
        return {"status": "ok", "payload": payload}


async def run_manual_smoke_test() -> ExecutedOrder:
    """Execute a manual market order via :func:`execute_market_order`."""

    state = BotState(
        autotrade_enabled=False,
        margin_mode="isolated",
        margin_asset="usdt",
        leverage=7,
        global_trade=GlobalTradeConfig(
            margin_usdt=75.0,
            lev_long=7,
            lev_short=9,
            isolated=True,
            hedge_mode=True,
        ),
    )
    client = FakeBingXClient()

    print("→ Manual trade smoke test")
    order = await execute_market_order(
        client,
        state=state,
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.005,
        position_side="LONG",
    )
    print("  symbol:", order.payload["symbol"])
    print("  side:", order.payload["side"])
    print("  quantity:", order.quantity)
    print("  leverage:", order.leverage)
    print("  price:", order.price)
    print()
    return order


async def run_autotrade_smoke_test() -> ExecutedOrder | None:
    """Prepare and execute an autotrade order using a fake TradingView alert."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="usdt",
        leverage=12,
        max_trade_size=0.02,
        global_trade=GlobalTradeConfig(
            margin_usdt=50.0,
            lev_long=12,
            lev_short=10,
            isolated=True,
            hedge_mode=True,
        ),
    )

    alert = {
        "symbol": "ETHUSDT",
        "side": "buy",
        "margin": 35,
        "clientOrderId": "demo-autotrade",
    }

    payload, error = _prepare_autotrade_order(alert, state)
    if error or not payload:
        print("→ Autotrade smoke test failed:", error)
        return None

    client = FakeBingXClient(mark_price=1_900.0)

    print("→ Autotrade smoke test")
    order = await execute_market_order(
        client,
        state=state,
        symbol=payload["symbol"],
        side=payload["side"],
        quantity=payload.get("quantity"),
        margin_usdt=payload.get("margin_usdt"),
        margin_mode=payload.get("margin_mode"),
        margin_coin=payload.get("margin_coin"),
        position_side=payload.get("position_side"),
        reduce_only=payload.get("reduce_only", False),
        client_order_id=payload.get("client_order_id"),
    )
    print("  symbol:", order.payload["symbol"])
    print("  side:", order.payload["side"])
    print("  quantity:", order.quantity)
    print("  leverage:", order.leverage)
    print("  price:", order.price)
    print()
    return order


async def main() -> None:
    """Run both smoke tests sequentially."""

    await run_manual_smoke_test()
    await run_autotrade_smoke_test()
    print("✓ Smoke tests completed. Inspect the printed payloads above.")


if __name__ == "__main__":
    asyncio.run(main())
