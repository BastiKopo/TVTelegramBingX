from __future__ import annotations

import asyncio

from pathlib import Path
import sys
import types

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object, Response=object)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tvtelegrambingx.bot import stop_loss_monitor
from tvtelegrambingx.config import Settings


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_chat_id="123",
        tradingview_secret=None,
        bingx_api_key=None,
        bingx_api_secret=None,
        bingx_base_url="https://open-api.bingx.com",
        bingx_recv_window=5000,
        bingx_default_quantity=None,
        dry_run=True,
        tradingview_webhook_enabled=False,
        tradingview_webhook_route="/webhook",
        tradingview_host="0.0.0.0",
        tradingview_port=443,
        tradingview_ssl_certfile=None,
        tradingview_ssl_keyfile=None,
        tradingview_ssl_ca_certs=None,
        trading_disable_weekends=False,
        trading_active_hours=None,
        trading_active_days=None,
    )


def test_stop_loss_disabled_after_tp1(monkeypatch):
    calls: list[tuple[str, str, float]] = []

    async def fake_mark_price(symbol: str) -> float:
        return 95.0

    async def fake_latest_price(symbol: str) -> float:
        return 95.0

    async def fake_place_order(*, symbol: str, side: str, qty: float, **kwargs):
        calls.append((symbol, side, qty))

    async def fake_round_quantity(symbol: str, quantity: float) -> float:
        return quantity

    async def fake_notify_stop_loss(**kwargs):
        return None

    monkeypatch.setattr(stop_loss_monitor.bingx_account, "get_mark_price", fake_mark_price)
    monkeypatch.setattr(stop_loss_monitor.bingx_client, "get_latest_price", fake_latest_price)
    monkeypatch.setattr(stop_loss_monitor.bingx_client, "place_order", fake_place_order)
    monkeypatch.setattr(stop_loss_monitor, "_round_quantity", fake_round_quantity)
    monkeypatch.setattr(stop_loss_monitor, "_notify_stop_loss", fake_notify_stop_loss)

    key = ("BTC-USDT", "LONG")
    stop_loss_monitor._STOP_STATE.clear()
    stop_loss_monitor._STOP_STATE[key] = stop_loss_monitor._StopState(
        entry_price=100.0,
        tp1_hit=True,
    )

    asyncio.run(
        stop_loss_monitor._maybe_close_position(
            settings=_settings(),
            symbol="BTC-USDT",
            position_side="LONG",
            quantity=1.0,
            entry_price=100.0,
            sl_percent=2.0,
            tp1_move_r=1.0,
            tp1_move_atr=0.0,
            tp1_sell_percent=25.0,
            tp2_move_r=2.0,
            tp2_move_atr=0.0,
            tp2_sell_percent=25.0,
            sl_to_entry_after_tp2=False,
        )
    )

    assert calls == []


def test_sl_moves_to_entry_after_tp2(monkeypatch):
    calls: list[tuple[str, str, float]] = []

    async def fake_place_order(*, symbol: str, side: str, qty: float, **kwargs):
        calls.append((symbol, side, qty))

    prices = iter([104.0, 100.0])

    async def fake_mark_price(symbol: str) -> float:
        return next(prices)

    async def fake_latest_price(symbol: str) -> float:
        return 0.0

    async def fake_round_quantity(symbol: str, quantity: float) -> float:
        return quantity

    async def fake_notify_stop_loss(**kwargs):
        return None

    monkeypatch.setattr(stop_loss_monitor.bingx_account, "get_mark_price", fake_mark_price)
    monkeypatch.setattr(stop_loss_monitor.bingx_client, "get_latest_price", fake_latest_price)
    monkeypatch.setattr(stop_loss_monitor.bingx_client, "place_order", fake_place_order)
    monkeypatch.setattr(stop_loss_monitor, "_round_quantity", fake_round_quantity)
    monkeypatch.setattr(stop_loss_monitor, "_notify_stop_loss", fake_notify_stop_loss)

    key = ("BTC-USDT", "LONG")
    stop_loss_monitor._STOP_STATE.clear()

    asyncio.run(
        stop_loss_monitor._maybe_close_position(
            settings=_settings(),
            symbol="BTC-USDT",
            position_side="LONG",
            quantity=1.0,
            entry_price=100.0,
            sl_percent=2.0,
            tp1_move_r=1.0,
            tp1_move_atr=0.0,
            tp1_sell_percent=25.0,
            tp2_move_r=2.0,
            tp2_move_atr=0.0,
            tp2_sell_percent=25.0,
            sl_to_entry_after_tp2=True,
        )
    )
    assert calls == []
    assert stop_loss_monitor._STOP_STATE[key].tp2_hit is True

    asyncio.run(
        stop_loss_monitor._maybe_close_position(
            settings=_settings(),
            symbol="BTC-USDT",
            position_side="LONG",
            quantity=1.0,
            entry_price=100.0,
            sl_percent=2.0,
            tp1_move_r=1.0,
            tp1_move_atr=0.0,
            tp1_sell_percent=25.0,
            tp2_move_r=2.0,
            tp2_move_atr=0.0,
            tp2_sell_percent=25.0,
            sl_to_entry_after_tp2=True,
        )
    )

    assert len(calls) == 1
