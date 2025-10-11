"""Tests for manual trading helpers and callbacks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import telegram_bot
from bot.state import BotState
from config import Settings


def _make_settings(position_mode: str = "hedge") -> Settings:
    return Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
        position_mode=position_mode,
    )


def test_build_manual_trade_keyboard_for_hedge_mode() -> None:
    """Manual trading buttons provide four hedge-mode actions."""

    alert = {"symbol": "LTCUSDT", "qty": 0.5, "margin": 25}
    markup = telegram_bot._build_manual_trade_keyboard(  # type: ignore[attr-defined]
        "alert1",
        alert,
        position_mode="hedge",
        settings=_make_settings("hedge"),
    )

    rows = markup.inline_keyboard
    assert len(rows) == 2
    assert [button.text for button in rows[0]] == ["🟢 Long öffnen", "⚪ Long schließen"]
    assert [button.text for button in rows[1]] == ["🔴 Short öffnen", "⚫ Short schließen"]

    first_data = rows[0][0].callback_data
    assert isinstance(first_data, str) and first_data.startswith("manual:")
    payload = first_data[len("manual:") :]
    segments = payload.split(":")
    assert len(segments) == 3
    alert_id, action_code, mode_code = segments
    assert alert_id
    assert action_code == "LO"
    assert mode_code == "H"
    assert len(first_data.encode("utf-8")) <= 64


def test_build_manual_trade_keyboard_for_oneway_mode() -> None:
    """Manual trading buttons stay in buy/sell layout for one-way mode."""

    alert = {"symbol": "ETHUSDT", "qty": "1"}
    markup = telegram_bot._build_manual_trade_keyboard(  # type: ignore[attr-defined]
        "alert2",
        alert,
        position_mode="oneway",
        settings=_make_settings("oneway"),
    )

    rows = markup.inline_keyboard
    assert len(rows) == 1
    assert [button.text for button in rows[0]] == ["🟢 Kaufen", "🔴 Verkaufen"]

    sell_data = rows[0][1].callback_data
    assert isinstance(sell_data, str) and sell_data.startswith("manual:")
    assert sell_data.endswith(":LC:O")
    assert len(sell_data.encode("utf-8")) <= 64


def test_manual_trade_callback_applies_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual callbacks map actions to concrete BingX parameters."""

    async def runner() -> None:
        settings = _make_settings("hedge")
        state = BotState()
        state.global_trade.hedge_mode = True

        application = SimpleNamespace(
            bot_data={"settings": settings, "state": state},
            bot=SimpleNamespace(send_message=AsyncMock()),
        )

        alert_id = telegram_bot._store_manual_alert(
            application,
            {"symbol": "BTC/USDT", "qty": "1", "margin": "15"},
        )

        monkeypatch.setattr(
            telegram_bot,
            "_resolve_state_for_order",
            lambda app: (state, None),
        )

        captured: dict[str, object] = {}

        async def _fake_place_order(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            captured["alert"] = args[2]
            return True

        monkeypatch.setattr(telegram_bot, "_place_order_from_alert", _fake_place_order)

        query = SimpleNamespace(
            data=f"manual:{alert_id}:SC:H",
            answer=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(application=application)

        await telegram_bot._manual_trade_callback(update, context)

        alert_payload = captured["alert"]
        assert isinstance(alert_payload, dict)
        assert alert_payload["action"] == "SHORT_CLOSE"
        assert alert_payload["side"] == "BUY"
        assert alert_payload["reduceOnly"] is True
        assert alert_payload["positionSide"] == "SHORT"
        assert alert_payload["qty"] == "1"
        assert alert_payload["margin_usdt"] == "15"

        kwargs = captured["kwargs"]
        assert kwargs["failure_label"] == "Manueller Trade"
        assert kwargs["enforce_direction_rules"] is False

        query.answer.assert_awaited()

    asyncio.run(runner())


def test_manual_trade_command_uses_direction_for_position_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manual command payloads propagate explicit LONG/SHORT directions."""

    async def runner() -> None:
        settings = _make_settings("oneway")
        state = BotState()
        state.global_trade.hedge_mode = False

        application = SimpleNamespace(
            bot_data={"settings": settings, "state": state},
            bot=SimpleNamespace(send_message=AsyncMock()),
        )

        monkeypatch.setattr(
            telegram_bot,
            "_resolve_state_for_order",
            lambda app: (state, None),
        )

        captured: dict[str, object] = {}

        async def _fake_place_order(*args, **kwargs):
            captured["alert"] = args[2]
            captured["kwargs"] = kwargs
            return True

        monkeypatch.setattr(telegram_bot, "_place_order_from_alert", _fake_place_order)

        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=123),
        )
        context = SimpleNamespace(application=application)

        request = telegram_bot.ManualOrderRequest(
            symbol="LTCUSDT",
            quantity=0.5,
            margin=None,
            leverage=None,
            limit_price=None,
            time_in_force=None,
            reduce_only=None,
            direction="LONG",
            client_order_id=None,
        )

        await telegram_bot._execute_manual_trade_command(
            update,
            context,
            action="LONG_OPEN",
            request=request,
        )

        alert_payload = captured.get("alert")
        assert isinstance(alert_payload, dict)
        assert alert_payload["positionSide"] == "LONG"

        message.reply_text.assert_awaited_with("✅ Order angenommen.")

    asyncio.run(runner())
