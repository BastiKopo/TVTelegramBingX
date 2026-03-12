from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object, Response=object, Timeout=object)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tvtelegrambingx.bot import dynamic_tp_monitor
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


def test_dynamic_tp_triggers_only_one_level_per_cycle(monkeypatch):
    orders: list[tuple[str, str, float, str]] = []

    async def fake_mark_price(symbol: str) -> float:
        return 120.0

    async def fake_latest_price(symbol: str) -> float:
        return 120.0

    async def fake_round_quantity(symbol: str, quantity: float) -> float:
        return quantity

    async def fake_atr_percent(symbol: str, *, entry_price: float) -> float:
        return 0.0

    async def fake_notify_dynamic_tp(**kwargs):
        return None

    async def fake_place_order(*, symbol: str, side: str, qty: float, reduce_only: bool, position_side: str):
        orders.append((symbol, side, qty, position_side))

    monkeypatch.setattr(dynamic_tp_monitor.bingx_account, "get_mark_price", fake_mark_price)
    monkeypatch.setattr(dynamic_tp_monitor.bingx_client, "get_latest_price", fake_latest_price)
    monkeypatch.setattr(dynamic_tp_monitor.bingx_client, "place_order", fake_place_order)
    monkeypatch.setattr(dynamic_tp_monitor, "_round_quantity", fake_round_quantity)
    monkeypatch.setattr(dynamic_tp_monitor, "_get_atr_percent", fake_atr_percent)
    monkeypatch.setattr(dynamic_tp_monitor, "_notify_dynamic_tp", fake_notify_dynamic_tp)

    dynamic_tp_monitor._TRIGGER_STATE.clear()

    asyncio.run(
        dynamic_tp_monitor._maybe_reduce_position(
            settings=_settings(),
            symbol="BTC-USDT",
            position_side="LONG",
            quantity=1.0,
            entry_price=100.0,
            sl_percent=2.0,
            triggers=[
                (1, 1.0, 0.0, 25.0),
                (2, 2.0, 0.0, 25.0),
            ],
        )
    )

    assert len(orders) == 1
    assert orders[0][0] == "BTC-USDT"
    assert orders[0][1] == "SELL"

    state = dynamic_tp_monitor._TRIGGER_STATE[("BTC-USDT", "LONG")]
    assert state.triggered_levels == {1}
