"""Tests for autotrade order preparation."""

from __future__ import annotations

import sys
import asyncio
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

    class _DummyBotCommand:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _DummyUpdate:
        message = None

    sys.modules["telegram"] = SimpleNamespace(
        BotCommand=_DummyBotCommand,
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

    class _DummyContextTypes:
        DEFAULT_TYPE = object()

    sys.modules["telegram.ext"] = SimpleNamespace(
        Application=_DummyApplication,
        ApplicationBuilder=_DummyApplicationBuilder,
        CommandHandler=_DummyCommandHandler,
        ContextTypes=_DummyContextTypes,
    )

from bot.state import BotState, save_state
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


def test_prepare_autotrade_order_alert_overrides_all_sources() -> None:
    """Konfiguration aus dem TradingView-Alert hat die höchste Priorität."""

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
    assert payload["margin_mode"] == "CROSSED"
    assert payload["margin_coin"] == "BTC"
    assert payload["leverage"] == 50


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

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_margin_type(
            self,
            *,
            symbol: str,
            margin_mode: str,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            leverage: float,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            side: str | None = None,
            position_side: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "side": side,
                    "position_side": position_side,
                }
            )

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
        leverage=7.5,
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
    assert client.margin_calls == [
        {"symbol": "BTCUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BTCUSDT",
            "leverage": 7.5,
            "margin_mode": "ISOLATED",
            "margin_coin": "BUSD",
            "side": "BUY",
            "position_side": "LONG",
        }
    ]
    assert client.order_calls and client.order_calls[0]["margin_mode"] == "ISOLATED"


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

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_margin_type(
            self,
            *,
            symbol: str,
            margin_mode: str,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            leverage: float,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            side: str | None = None,
            position_side: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "side": side,
                    "position_side": position_side,
                }
            )

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
        "margin_mode": "ISOLATED",
        "margin_coin": "BUSD",
        "leverage": 15,
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
    assert client.margin_calls == [
        {"symbol": "ETHUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "ETHUSDT",
            "leverage": 15,
            "margin_mode": "ISOLATED",
            "margin_coin": "BUSD",
            "side": "BUY",
            "position_side": "LONG",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 15


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

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_margin_type(
            self,
            *,
            symbol: str,
            margin_mode: str,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            leverage: float,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            side: str | None = None,
            position_side: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "side": side,
                    "position_side": position_side,
                }
            )

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
        leverage=12,
    )
    state_file = tmp_path / "bot_state.json"
    save_state(state_file, persisted_state)

    stale_state = BotState(
        autotrade_enabled=False,
        margin_mode="cross",
        margin_asset="usdt",
        leverage=3,
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
    assert client.margin_calls == [
        {"symbol": "BNBUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BNBUSDT",
            "leverage": 12,
            "margin_mode": "ISOLATED",
            "margin_coin": "BUSD",
            "side": "BUY",
            "position_side": "LONG",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 12


def test_execute_autotrade_prefers_alert_configuration(monkeypatch) -> None:
    """Overrides aus dem Alert werden an BingX weitergegeben."""

    class DummyBot:
        async def send_message(self, *args, **kwargs) -> None:
            return None

    class RecordingClient:
        def __init__(self, *args, **kwargs) -> None:
            self.margin_calls: list[dict[str, Any]] = []
            self.leverage_calls: list[dict[str, Any]] = []
            self.order_calls: list[dict[str, Any]] = []

        async def __aenter__(self) -> "RecordingClient":
            instances.append(self)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def set_margin_type(
            self,
            *,
            symbol: str,
            margin_mode: str,
            margin_coin: str | None = None,
        ) -> None:
            self.margin_calls.append(
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                }
            )

        async def set_leverage(
            self,
            *,
            symbol: str,
            leverage: float,
            margin_mode: str | None = None,
            margin_coin: str | None = None,
            side: str | None = None,
            position_side: str | None = None,
        ) -> None:
            self.leverage_calls.append(
                {
                    "symbol": symbol,
                    "leverage": leverage,
                    "margin_mode": margin_mode,
                    "margin_coin": margin_coin,
                    "side": side,
                    "position_side": position_side,
                }
            )

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

    state = BotState(autotrade_enabled=True, margin_mode="cross", margin_asset="usdt", leverage=3)

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
    assert client.margin_calls == [
        {"symbol": "BTCUSDT", "margin_mode": "ISOLATED", "margin_coin": "BUSD"}
    ]
    assert client.leverage_calls == [
        {
            "symbol": "BTCUSDT",
            "leverage": 25,
            "margin_mode": "ISOLATED",
            "margin_coin": "BUSD",
            "side": "BUY",
            "position_side": "LONG",
        }
    ]
    assert client.order_calls and client.order_calls[0]["leverage"] == 25


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
