"""Tests for autotrade order preparation."""

from __future__ import annotations

import sys
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

from bot.state import BotState
from bot.telegram_bot import (
    _extract_symbol_from_alert,
    _infer_symbol_from_positions,
    _prepare_autotrade_order,
)


def make_alert(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": "0.01",
    }
    payload.update(overrides)
    return payload


def test_prepare_autotrade_order_uses_state_margin_and_leverage() -> None:
    """Margin- und Leverage-Einstellungen stammen aus dem gespeicherten Zustand."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        leverage=7.5,
    )

    alert = make_alert(margin_mode="CROSSED", leverage=25)

    payload, error = _prepare_autotrade_order(alert, state)

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
