import asyncio

from bot.state import BotState
from integrations.bingx_client import BingXClientError
from services.trading import execute_market_order, invalidate_symbol_configuration


class _ModeSyncFailureClient:
    """Minimal BingX client stub for testing position-side handling."""

    def __init__(self) -> None:
        self.market_calls: list[dict[str, object]] = []

    async def get_position_mode(self) -> bool:
        raise BingXClientError("position mode unavailable")

    async def set_position_mode(self, hedge: bool) -> None:
        raise BingXClientError("cannot update mode")

    async def set_margin_mode(self, *, symbol: str, marginMode: str, marginCoin: str | None = None) -> None:  # noqa: N803
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
        return 75.0

    async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        return {"step_size": 0.001, "min_qty": 0.001}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_keeps_position_side_when_mode_unknown() -> None:
    """Explicit LONG/SHORT instructions survive temporary mode sync issues."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _ModeSyncFailureClient()
        state = BotState()
        state.global_trade.hedge_mode = False
        state.global_trade.lev_long = 3
        state.global_trade.lev_short = 3

        await execute_market_order(
            client,
            state=state,
            symbol="LTC-USDT",
            side="SELL",
            quantity=1.0,
            position_side="SHORT",
        )

        assert client.market_calls, "Market order was not forwarded to the client"
        assert client.market_calls[0]["positionSide"] == "SHORT"

    asyncio.run(runner())


class _HedgeReduceOnlyClient:
    """Client stub capturing reduceOnly flags while running in hedge mode."""

    def __init__(self) -> None:
        self.market_calls: list[dict[str, object]] = []

    async def get_position_mode(self) -> bool:
        return True

    async def set_position_mode(self, hedge: bool) -> None:
        return None

    async def set_margin_mode(
        self, *, symbol: str, marginMode: str, marginCoin: str | None = None
    ) -> None:  # noqa: N803
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
        return 25_000.0

    async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        return {"step_size": 0.001, "min_qty": 0.001}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_omits_reduce_only_in_hedge_mode() -> None:
    """Reduce-only flags are not forwarded to the API in hedge mode."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _HedgeReduceOnlyClient()
        state = BotState()
        state.global_trade.hedge_mode = True
        state.global_trade.lev_long = 5
        state.global_trade.lev_short = 5

        await execute_market_order(
            client,
            state=state,
            symbol="ETH-USDT",
            side="SELL",
            quantity=1.0,
            position_side="LONG",
            reduce_only=True,
        )

        assert client.market_calls, "Expected market order to be executed"
        call = client.market_calls[0]
        assert call["positionSide"] == "LONG"
        assert call["reduceOnly"] is False

    asyncio.run(runner())
