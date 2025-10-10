"""Tests for the webhook dispatcher helper utilities."""

import asyncio
from unittest.mock import AsyncMock

from bot.state import BotState, GlobalTradeConfig
from services.trading import ExecutedOrder
from webhook import dispatcher


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
            mock_client.place_market.return_value = {"status": "success"}
            mock_client.order_calls = []
            mock_client.get_position_mode.return_value = True

            dispatcher.configure_trading_context(bot_state=state, bingx_client=mock_client)

            result = await dispatcher.place_signal_order("BTC-USDT", "buy")

            assert isinstance(result, ExecutedOrder)
            assert result.response == {"status": "success"}
            mock_client.get_position_mode.assert_awaited_once()
            mock_client.set_position_mode.assert_not_awaited()
            mock_client.set_margin_mode.assert_awaited_once_with(
                symbol="BTC-USDT", marginMode="ISOLATED", marginCoin="USDT"
            )
            mock_client.set_leverage.assert_awaited_once_with(
                symbol="BTC-USDT",
                lev_long=5,
                lev_short=7,
                hedge=True,
                margin_coin="USDT",
            )
            mock_client.place_market.assert_awaited_once()
            args, kwargs = mock_client.place_market.call_args
            assert kwargs["positionSide"] == "LONG"
            assert kwargs["reduceOnly"] is False
        finally:
            dispatcher.configure_trading_context(bot_state=original_state, bingx_client=original_client)

    asyncio.run(runner())

