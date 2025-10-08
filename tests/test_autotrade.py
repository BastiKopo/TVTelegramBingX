"""Tests for autotrade order preparation."""

from __future__ import annotations

import sys
import asyncio
import math
from types import SimpleNamespace
from typing import Any


if "httpx" not in sys.modules:
    class _DummyResponse:
        def __init__(self) -> None:
            self.status_code = 200

        def json(self) -> dict[str, Any]:  # pragma: no cover - defensive stub
            return {"code": 0, "data": {}}

    class _DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs

        async def request(self, *args, **kwargs):  # pragma: no cover - defensive stub
            return _DummyResponse()

        async def aclose(self) -> None:
            return None

    sys.modules["httpx"] = SimpleNamespace(AsyncClient=_DummyAsyncClient)


if "telegram" not in sys.modules:
    class _DummyReplyKeyboardMarkup:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyInlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, **kwargs) -> None:
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

    class _DummyUpdate:
        message = None

    sys.modules["telegram"] = SimpleNamespace(
        BotCommand=_DummyBotCommand,
        InlineKeyboardButton=_DummyInlineKeyboardButton,
        InlineKeyboardMarkup=_DummyInlineKeyboardMarkup,
        ReplyKeyboardMarkup=_DummyReplyKeyboardMarkup,
        Update=_DummyUpdate,
    )


if "telegram.ext" not in sys.modules:
    class _DummyApplication:
        def __init__(self) -> None:
            self.bot_data: dict[str, Any] = {}
            self.bot = SimpleNamespace(
                set_my_commands=lambda *args, **kwargs: None,
                send_message=lambda *args, **kwargs: None,
            )
            self.job_queue = None

        def add_handler(self, handler) -> None:  # pragma: no cover - only for imports
            self.bot_data.setdefault("handlers", []).append(handler)

    class _DummyApplicationBuilder:
        def __init__(self) -> None:
            self._token = None

        def token(self, value: str) -> "_DummyApplicationBuilder":
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

    sys.modules["telegram.ext"] = SimpleNamespace(
        Application=_DummyApplication,
        ApplicationBuilder=_DummyApplicationBuilder,
        CallbackQueryHandler=_DummyCallbackQueryHandler,
        CommandHandler=_DummyCommandHandler,
        ContextTypes=_DummyContextTypes,
    )

from bot.state import BotState, GlobalTradeConfig, save_state
from bot.telegram_bot import (
    _execute_autotrade,
    _extract_symbol_from_alert,
    _infer_symbol_from_positions,
    _prepare_autotrade_order,
)
from config import Settings


def make_alert(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": "0.01",
    }
    payload.update(overrides)
    return payload


def test_prepare_autotrade_order_defaults_to_state_configuration() -> None:
    """Ohne Overrides verwendet der Autotrade die gespeicherten Einstellungen."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        leverage=7.5,
    )

    payload, error = _prepare_autotrade_order(make_alert(), state)

    assert error is None
    assert payload is not None
    assert payload["margin_mode"] == "ISOLATED"
    assert payload["leverage"] == 7.5
    assert payload["margin_coin"] == "BUSD"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["side"] == "BUY"
    assert payload["quantity"] == 0.01
    assert payload["position_side"] == "LONG"


def test_prepare_autotrade_order_prefers_snapshot_over_state() -> None:
    """Persisted snapshot overrides ensure BingX receives up-to-date config."""

    state = BotState(autotrade_enabled=True, margin_mode="cross", margin_asset="usdt", leverage=3)
    snapshot = {"margin_mode": "isolated", "margin_coin": "busd", "leverage": "12"}

    payload, error = _prepare_autotrade_order(make_alert(), state, snapshot)

    assert error is None
    assert payload is not None
    assert payload["margin_mode"] == "ISOLATED"
    assert payload["leverage"] == 12
    assert payload["margin_coin"] == "BUSD"
    assert payload["position_side"] == "LONG"


def test_prepare_autotrade_order_ignores_alert_overrides() -> None:
    """TradingView-Signale überschreiben Margin- und Leverage-Werte nicht."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="cross",
        margin_asset="usdt",
        leverage=3,
    )
    snapshot = {"margin_mode": "isolated", "margin_coin": "busd", "leverage": "12"}
    alert = make_alert(marginType="cross", marginCoin="btc", leverage=50)

    payload, error = _prepare_autotrade_order(alert, state, snapshot)

    assert error is None
    assert payload is not None
    assert payload["margin_mode"] == "ISOLATED"
    assert payload["margin_coin"] == "BUSD"
    assert payload["leverage"] == 12


def test_prepare_autotrade_order_ignores_numeric_margin_coin() -> None:
    """Numeric marginCoin overrides from TradingView alerts are ignored."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="usdt",
        leverage=7.5,
    )
    alert = make_alert(marginCoin="5")

    payload, error = _prepare_autotrade_order(alert, state)

    assert error is None
    assert payload is not None
    assert payload["margin_coin"] == "USDT"


def test_prepare_autotrade_order_supports_margin_budget_without_quantity() -> None:
    """A margin budget without quantity defers size calculation to execution time."""

    state = BotState(autotrade_enabled=True, leverage=12)
    alert = {"symbol": "BTCUSDT", "side": "buy", "margin": "50"}

    payload, error = _prepare_autotrade_order(alert, state)

    assert error is None
    assert payload is not None
    assert payload["quantity"] is None
    assert payload["margin_usdt"] == 50.0


def test_prepare_autotrade_order_reads_numeric_margin_coin_as_budget() -> None:
    """Numeric marginCoin payloads are re-used as margin budgets."""

    state = BotState(autotrade_enabled=True, leverage=10)
    alert = {"symbol": "ETHUSDT", "side": "buy", "marginCoin": "12.5"}

    payload, error = _prepare_autotrade_order(alert, state)

    assert error is None
    assert payload is not None
    assert payload["margin_usdt"] == 12.5


def test_prepare_autotrade_order_respects_position_side_override() -> None:
    """PositionSide aus dem Signal wird direkt übernommen."""

    state = BotState(autotrade_enabled=True)
    alert = make_alert(positionSide="short")

    payload, error = _prepare_autotrade_order(alert, state)

    assert error is None
    assert payload is not None
    assert payload["position_side"] == "SHORT"


def test_prepare_autotrade_order_flips_position_side_when_reducing() -> None:
    """Reduce-Only-Trades adressieren die bestehende Gegenposition."""

    state = BotState(autotrade_enabled=True)
    alert = make_alert(side="sell", reduceOnly=True)

    payload, error = _prepare_autotrade_order(alert, state)

    assert error is None
    assert payload is not None
    assert payload["position_side"] == "LONG"


def test_prepare_autotrade_order_respects_long_only_setting() -> None:
    """Long-only configuration skips short signals."""

    state = BotState(autotrade_enabled=True, autotrade_direction="long")
    alert = make_alert(side="sell")

    payload, error = _prepare_autotrade_order(alert, state)

    assert payload is None
    assert error is not None
    assert "Nur Long" in error


def test_prepare_autotrade_order_respects_short_only_setting() -> None:
    """Short-only configuration skips long signals."""

    state = BotState(autotrade_enabled=True, autotrade_direction="short")
    alert = make_alert(side="buy")

    payload, error = _prepare_autotrade_order(alert, state)

    assert payload is None
    assert error is not None
    assert "Nur Short" in error


def test_execute_autotrade_updates_margin_and_leverage(monkeypatch) -> None:
    """Autotrade synchronises leverage and margin settings before trading."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.margin_calls: list[dict[str, Any]] = []
            self.leverage_calls: list[dict[str, Any]] = []
            self.order_calls: list[dict[str, Any]] = []
            self.position_mode_calls: list[bool] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_position_mode(self, hedge: bool) -> None:
            self.position_mode_calls.append(hedge)

        async def set_margin_type(
            self,
            *,
            symbol: str,
            isolated: bool | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
        ) -> None:
            mode = margin_mode
            if mode is None and isolated is not None:
                mode = "ISOLATED" if isolated else "CROSSED"
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            lev_long: int | float | None = None,
            lev_short: int | float | None = None,
            hedge: bool | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "lev_long": lev_long,
                    "lev_short": lev_short,
                    "hedge": hedge,
                    "margin_coin": margin_coin,
                }
            )

        async def get_mark_price(self, symbol: str) -> float:
            return 22_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 30_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 18_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 22_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 30_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 18_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def get_mark_price(self, symbol: str) -> float:
            return 25_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def place_order(
            self,
            *,
            symbol: str,
            side: str,
            position_side: str | None = None,
            quantity: float,
            order_type: str = "MARKET",
            price: float | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            leverage: float | None = None,
            reduce_only: bool | None = None,
            client_order_id: str | None = None,
        ) -> dict[str, Any]:
            self.order_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "price": price,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "leverage": leverage,
                    "reduce_only": reduce_only,
                    "client_order_id": client_order_id,
                }
            )
            return {"orderId": "1", "status": "FILLED"}

    instances: list[RecordingClient] = []

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        global_trade=GlobalTradeConfig(
            margin_usdt=50,
            lev_long=8,
            lev_short=6,
            isolated=True,
            hedge_mode=True,
        ),
    )

    monkeypatch.setattr("bot.telegram_bot.BingXClient", RecordingClient)
    monkeypatch.setattr("bot.telegram_bot.load_state_snapshot", lambda: None)
    monkeypatch.setattr("bot.telegram_bot.load_state", lambda path: state)

    application = SimpleNamespace(bot=DummyBot(), bot_data={"state": state})
    settings = Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
    )

    alert = {"symbol": "BTCUSDT", "side": "buy", "quantity": 0.5}

    asyncio.run(_execute_autotrade(application, settings, alert))

    assert instances, "Expected BingXClient to be instantiated"
    client = instances[0]
    assert client.position_mode_calls == [True]
    assert client.margin_calls == [
        {"symbol": "BTCUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BTCUSDT",
            "lev_long": 8,
            "lev_short": 6,
            "hedge": True,
            "margin_coin": "BUSD",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 8


def test_execute_autotrade_calculates_quantity_from_margin(monkeypatch) -> None:
    """Missing quantities are derived from the configured margin budget."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.order_calls: list[dict[str, Any]] = []
            self.position_mode_calls: list[bool] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_position_mode(self, hedge: bool) -> None:
            self.position_mode_calls.append(hedge)

        async def set_margin_type(
            self,
            *,
            symbol: str,
            isolated: bool | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
        ) -> None:
            return None

        async def set_leverage(
            self,
            *,
            symbol: str,
            lev_long: int | float | None = None,
            lev_short: int | float | None = None,
            hedge: bool | None = None,
            margin_coin: str | None = None,
        ) -> None:
            return None

        async def get_mark_price(self, symbol: str) -> float:
            return 20_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def place_order(
            self,
            *,
            symbol: str,
            side: str,
            position_side: str | None = None,
            quantity: float,
            order_type: str = "MARKET",
            price: float | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            leverage: float | None = None,
            reduce_only: bool | None = None,
            client_order_id: str | None = None,
        ) -> dict[str, Any]:
            self.order_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "leverage": leverage,
                }
            )
            return {"orderId": "99", "status": "FILLED"}

    instances: list[RecordingClient] = []

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        global_trade=GlobalTradeConfig(
            margin_usdt=25,
            lev_long=10,
            lev_short=10,
            isolated=True,
            hedge_mode=True,
        ),
    )

    monkeypatch.setattr("bot.telegram_bot.BingXClient", RecordingClient)
    monkeypatch.setattr("bot.telegram_bot.load_state_snapshot", lambda: None)
    monkeypatch.setattr("bot.telegram_bot.load_state", lambda path: state)

    application = SimpleNamespace(bot=DummyBot(), bot_data={"state": state})
    settings = Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
    )

    alert = {"symbol": "BTCUSDT", "side": "buy", "margin": 25}

    asyncio.run(_execute_autotrade(application, settings, alert))

    assert instances, "Expected BingXClient to be instantiated"
    order = instances[0].order_calls[0]
    assert math.isclose(order["quantity"], 0.012, rel_tol=1e-9)
    assert order["margin_mode"] == "ISOLATED"
    assert order["margin_coin"] == "BUSD"
    assert order["leverage"] == 10


def test_execute_autotrade_uses_snapshot_configuration(monkeypatch) -> None:
    """Persisted state.json overrides drive BingX order configuration."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.margin_calls: list[dict[str, Any]] = []
            self.leverage_calls: list[dict[str, Any]] = []
            self.order_calls: list[dict[str, Any]] = []
            self.position_mode_calls: list[bool] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_position_mode(self, hedge: bool) -> None:
            self.position_mode_calls.append(hedge)

        async def set_margin_type(
            self,
            *,
            symbol: str,
            isolated: bool | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
        ) -> None:
            mode = margin_mode if margin_mode is not None else ("ISOLATED" if isolated else "CROSSED")
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            lev_long: int | float | None = None,
            lev_short: int | float | None = None,
            hedge: bool | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "lev_long": lev_long,
                    "lev_short": lev_short,
                    "hedge": hedge,
                    "margin_coin": margin_coin,
                }
            )

        async def get_mark_price(self, symbol: str) -> float:
            return 18_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def place_order(
            self,
            *,
            symbol: str,
            side: str,
            position_side: str | None = None,
            quantity: float,
            order_type: str = "MARKET",
            price: float | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            leverage: float | None = None,
            reduce_only: bool | None = None,
            client_order_id: str | None = None,
        ) -> dict[str, Any]:
            self.order_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "price": price,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "leverage": leverage,
                    "reduce_only": reduce_only,
                    "client_order_id": client_order_id,
                }
            )
            return {"orderId": "42", "status": "FILLED"}

    instances: list[RecordingClient] = []

    snapshot = {
        "global_trade": {
            "margin_usdt": 75,
            "lev_long": 12,
            "lev_short": 4,
            "isolated": False,
            "hedge_mode": False,
        },
        "margin_mode": "CROSSED",
        "margin_coin": "BUSD",
        "margin_asset": "BUSD",
    }

    state = BotState(autotrade_enabled=True)

    monkeypatch.setattr("bot.telegram_bot.BingXClient", RecordingClient)
    monkeypatch.setattr("bot.telegram_bot.load_state_snapshot", lambda: snapshot)
    monkeypatch.setattr("bot.telegram_bot.load_state", lambda path: state)

    application = SimpleNamespace(bot=DummyBot(), bot_data={"state": state})
    settings = Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
    )

    alert = {"symbol": "ETHUSDT", "side": "buy", "quantity": 1}

    asyncio.run(_execute_autotrade(application, settings, alert))

    assert instances, "Expected BingXClient to be instantiated"
    client = instances[0]
    assert client.position_mode_calls == [False]
    assert client.margin_calls == [
        {"symbol": "ETHUSDT", "margin_mode": "CROSSED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "ETHUSDT",
            "lev_long": 12,
            "lev_short": 4,
            "hedge": False,
            "margin_coin": "BUSD",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 12


def test_execute_autotrade_uses_persisted_state_when_memory_stale(tmp_path, monkeypatch) -> None:
    """Persisted bot_state.json values are respected even if in-memory state lags."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.margin_calls: list[dict[str, Any]] = []
            self.leverage_calls: list[dict[str, Any]] = []
            self.order_calls: list[dict[str, Any]] = []
            self.position_mode_calls: list[bool] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_position_mode(self, hedge: bool) -> None:
            self.position_mode_calls.append(hedge)

        async def set_margin_type(
            self,
            *,
            symbol: str,
            isolated: bool | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": (
                        margin_mode
                        if margin_mode is not None
                        else ("ISOLATED" if isolated else "CROSSED")
                    ),
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            lev_long: int | float | None = None,
            lev_short: int | float | None = None,
            hedge: bool | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "lev_long": lev_long,
                    "lev_short": lev_short,
                    "hedge": hedge,
                    "margin_coin": margin_coin,
                }
            )

        async def get_mark_price(self, symbol: str) -> float:
            return 30_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def place_order(
            self,
            *,
            symbol: str,
            side: str,
            position_side: str | None = None,
            quantity: float,
            order_type: str = "MARKET",
            price: float | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            leverage: float | None = None,
            reduce_only: bool | None = None,
            client_order_id: str | None = None,
        ) -> dict[str, Any]:
            self.order_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "price": price,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "leverage": leverage,
                    "reduce_only": reduce_only,
                    "client_order_id": client_order_id,
                }
            )
            return {"orderId": "7", "status": "FILLED"}

    instances: list[RecordingClient] = []

    persisted_state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        global_trade=GlobalTradeConfig(
            margin_usdt=60,
            lev_long=12,
            lev_short=12,
            isolated=True,
            hedge_mode=True,
        ),
    )
    state_file = tmp_path / "bot_state.json"
    save_state(state_file, persisted_state)

    stale_state = BotState(
        autotrade_enabled=False,
        margin_mode="cross",
        margin_asset="usdt",
        global_trade=GlobalTradeConfig(
            margin_usdt=5,
            lev_long=3,
            lev_short=3,
            isolated=False,
            hedge_mode=False,
        ),
    )

    monkeypatch.setattr("bot.telegram_bot.BingXClient", RecordingClient)
    monkeypatch.setattr("bot.telegram_bot.load_state_snapshot", lambda: None)

    application = SimpleNamespace(
        bot=DummyBot(),
        bot_data={"state": stale_state, "state_file": state_file},
    )
    settings = Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
    )

    alert = {"symbol": "BNBUSDT", "side": "buy", "quantity": 2}

    asyncio.run(_execute_autotrade(application, settings, alert))

    assert instances, "Expected BingXClient to be instantiated"
    client = instances[0]
    assert client.position_mode_calls == [True]
    assert client.margin_calls == [
        {"symbol": "BNBUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BNBUSDT",
            "lev_long": 12,
            "lev_short": 12,
            "hedge": True,
            "margin_coin": "BUSD",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 12


def test_execute_autotrade_ignores_alert_configuration(monkeypatch) -> None:
    """Autotrade nutzt trotz Alert-Einstellungen weiterhin den gespeicherten Zustand."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.margin_calls: list[dict[str, Any]] = []
            self.leverage_calls: list[dict[str, Any]] = []
            self.order_calls: list[dict[str, Any]] = []
            self.position_mode_calls: list[bool] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_position_mode(self, hedge: bool) -> None:
            self.position_mode_calls.append(hedge)

        async def set_margin_type(
            self,
            *,
            symbol: str,
            isolated: bool | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": (
                        margin_mode
                        if margin_mode is not None
                        else ("ISOLATED" if isolated else "CROSSED")
                    ),
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            lev_long: int | float | None = None,
            lev_short: int | float | None = None,
            hedge: bool | None = None,
            margin_coin: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "lev_long": lev_long,
                    "lev_short": lev_short,
                    "hedge": hedge,
                    "margin_coin": margin_coin,
                }
            )

        async def get_mark_price(self, symbol: str) -> float:
            return 22_000.0

        async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
            return {"step_size": 0.001, "min_qty": 0.001}

        async def place_order(
            self,
            *,
            symbol: str,
            side: str,
            position_side: str | None = None,
            quantity: float,
            order_type: str = "MARKET",
            price: float | None = None,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            leverage: float | None = None,
            reduce_only: bool | None = None,
            client_order_id: str | None = None,
        ) -> dict[str, Any]:
            self.order_calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "price": price,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "leverage": leverage,
                    "reduce_only": reduce_only,
                    "client_order_id": client_order_id,
                }
            )
            return {"orderId": "1", "status": "FILLED"}

    instances: list[RecordingClient] = []

    state = BotState(
        autotrade_enabled=True,
        margin_mode="cross",
        margin_asset="usdt",
        global_trade=GlobalTradeConfig(
            margin_usdt=30,
            lev_long=3,
            lev_short=3,
            isolated=False,
            hedge_mode=False,
        ),
    )

    monkeypatch.setattr("bot.telegram_bot.BingXClient", RecordingClient)
    monkeypatch.setattr("bot.telegram_bot.load_state_snapshot", lambda: None)
    monkeypatch.setattr("bot.telegram_bot.load_state", lambda path: state)

    application = SimpleNamespace(bot=DummyBot(), bot_data={"state": state})
    settings = Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
    )

    alert = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": 0.5,
        "marginMode": "isolated",
        "marginCoin": "busd",
        "leverage": 25,
    }

    asyncio.run(_execute_autotrade(application, settings, alert))

    assert instances, "Expected BingXClient to be instantiated"
    client = instances[0]
    assert client.position_mode_calls == [False]
    assert client.margin_calls == [
        {"symbol": "BTCUSDT", "margin_mode": "CROSSED", "margin_coin": "USDT"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BTCUSDT",
            "lev_long": 3,
            "lev_short": 3,
            "hedge": False,
            "margin_coin": "USDT",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 3


def test_extract_symbol_from_strategy_block() -> None:
    """Symbols können aus dem Strategy-Block extrahiert werden."""

    alert = {"strategy": {"symbol": "BINANCE:ethusdt"}}

    assert _extract_symbol_from_alert(alert) == "ETHUSDT"


def test_infer_symbol_from_positions_payload() -> None:
    """Symbols werden aus Positionslisten korrekt erkannt."""

    payload = [
        {"symbol": "XRPUSDT", "size": "10"},
        {"symbol": "BTCUSDT", "size": "1"},
    ]

    assert _infer_symbol_from_positions(payload) == "XRPUSDT"
