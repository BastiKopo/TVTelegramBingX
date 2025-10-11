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
    assert "act=LONG_OPEN" in first_data
    assert "sym=LTC-USDT" in first_data
    assert "qty=0.5" in first_data
    assert "margin=25" in first_data


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
    assert isinstance(sell_data, str) and "act=LONG_CLOSE" in sell_data
    assert "sym=ETH-USDT" in sell_data


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

        alert_id = telegram_bot._store_manual_alert(application, {"symbol": "BTCUSDT"})

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
            data=(
                f"manual:alert={alert_id}&act=SHORT_CLOSE&sym=BTC-USDT&qty=1&margin=15"
            ),
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
