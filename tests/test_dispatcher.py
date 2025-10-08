"""Tests for the webhook dispatcher helper utilities."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from bot.state import BotState, GlobalTradeConfig
from integrations.bingx_client import calc_order_qty
from webhook import dispatcher


def test_calc_order_qty_rounds_and_applies_minimum() -> None:
    """The helper respects exchange step sizes and minimum quantities."""

    quantity = calc_order_qty(
        price=25_000,
        margin_usdt=52,
        leverage=5,
        step_size=0.001,
        min_qty=0.002,
    )

    assert quantity == pytest.approx(0.01)

    with pytest.raises(ValueError):
        calc_order_qty(
            price=40_000,
            margin_usdt=5,
            leverage=1,
            step_size=0.001,
            min_qty=0.01,
        )


def test_place_signal_order_executes_market_order() -> None:
    """Orders are placed using the configured trading context."""

    async def runner() -> None:
        original_state = dispatcher.state
        original_client = dispatcher.client

        try:
            state = BotState(
                margin_mode="isolated",
                margin_asset="usdt",
                global_trade=GlobalTradeConfig(
                    margin_usdt=100,
                    lev_long=5,
                    lev_short=7,
                    isolated=True,
                    hedge_mode=True,
                ),
            )

            mock_client: AsyncMock = AsyncMock()
            mock_client.get_mark_price.return_value = 25_000.0
            mock_client.get_symbol_filters.return_value = {"min_qty": 0.001, "step_size": 0.001}
            mock_client.place_order.return_value = {"status": "success"}

            dispatcher.configure_trading_context(bot_state=state, bingx_client=mock_client)

            result = await dispatcher.place_signal_order("BTC-USDT", "buy")

            assert result == {"status": "success"}
            mock_client.set_position_mode.assert_awaited_once_with(True)
            mock_client.set_margin_type.assert_awaited_once_with(
                symbol="BTC-USDT", isolated=True, margin_coin="USDT"
            )
            mock_client.set_leverage.assert_awaited_once_with(
                symbol="BTC-USDT",
                lev_long=5,
                lev_short=7,
                hedge=True,
                margin_coin="USDT",
            )
            mock_client.place_order.assert_awaited_once()
            args, kwargs = mock_client.place_order.call_args
            assert kwargs["position_side"] == "LONG"
            assert kwargs["order_type"] == "MARKET"
            assert kwargs["reduce_only"] is False
        finally:
            dispatcher.configure_trading_context(bot_state=original_state, bingx_client=original_client)

    asyncio.run(runner())

