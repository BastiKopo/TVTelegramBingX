import asyncio

import pytest

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

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, object]:
        return {"code": 0, "data": []}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
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
        assert client.market_calls[0]["closePosition"] is False

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

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, object]:
        return {"code": 0, "data": []}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
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
        assert call["closePosition"] is False

    asyncio.run(runner())


class _HedgeModeStuckClient:
    """Client stub simulating a hedge mode that refuses to switch off."""

    def __init__(self) -> None:
        self.market_calls: list[dict[str, object]] = []
        self.mode_queries: int = 0

    async def get_position_mode(self) -> bool:
        self.mode_queries += 1
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
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_rechecks_mode_before_reduce_only() -> None:
    """Reduce-only orders confirm the final position mode before execution."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _HedgeModeStuckClient()
        state = BotState()
        state.global_trade.hedge_mode = False
        state.global_trade.lev_long = 5
        state.global_trade.lev_short = 5

        await execute_market_order(
            client,
            state=state,
            symbol="BTC-USDT",
            side="SELL",
            quantity=1.0,
            reduce_only=True,
        )

        assert client.market_calls, "Expected market order to be executed"
        call = client.market_calls[0]
        assert call["positionSide"] == "SHORT"
        assert call["reduceOnly"] is False
        assert client.mode_queries >= 2

    asyncio.run(runner())


class _OneWayClosePositionClient:
    """Client stub capturing closePosition flags in one-way mode."""

    def __init__(self) -> None:
        self.market_calls: list[dict[str, object]] = []

    async def get_position_mode(self) -> bool:
        return False

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

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, object]:
        return {"code": 0, "data": []}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_sets_close_position_in_oneway_mode() -> None:
    """Closing trades in one-way mode should toggle the closePosition flag."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _OneWayClosePositionClient()
        state = BotState()
        state.global_trade.hedge_mode = False
        state.global_trade.lev_long = 4
        state.global_trade.lev_short = 4

        await execute_market_order(
            client,
            state=state,
            symbol="ETH-USDT",
            side="SELL",
            quantity=1.0,
            reduce_only=True,
        )

        assert client.market_calls, "Expected market order to be executed"
        call = client.market_calls[0]
        assert call["positionSide"] == "BOTH"
        assert call["reduceOnly"] is True
        assert call["closePosition"] is True

    asyncio.run(runner())


class _ForceSyncTrackingClient:
    """Client stub capturing margin/leverage synchronisation calls."""

    def __init__(self) -> None:
        self.margin_calls: list[dict[str, object]] = []
        self.leverage_calls: list[dict[str, object]] = []
        self.market_calls: list[dict[str, object]] = []

    async def get_position_mode(self) -> bool:
        return True

    async def set_position_mode(self, hedge: bool) -> None:
        return None

    async def set_margin_mode(
        self, *, symbol: str, marginMode: str, marginCoin: str | None = None
    ) -> None:  # noqa: N803
        self.margin_calls.append(
            {"symbol": symbol, "marginMode": marginMode, "marginCoin": marginCoin}
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
        return 20_000.0

    async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        return {"step_size": 0.001, "min_qty": 0.001}

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, object]:
        return {"code": 0, "data": []}

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_forces_sync_for_open_orders() -> None:
    """Margin and leverage are synchronised before every opening trade."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _ForceSyncTrackingClient()
        state = BotState()
        state.global_trade.hedge_mode = True
        state.global_trade.lev_long = 6
        state.global_trade.lev_short = 8
        state.global_trade.margin_usdt = 15

        await execute_market_order(
            client,
            state=state,
            symbol="BTC-USDT",
            side="BUY",
            quantity=None,
            reduce_only=False,
        )

        await execute_market_order(
            client,
            state=state,
            symbol="BTC-USDT",
            side="BUY",
            quantity=None,
            reduce_only=False,
        )

        assert len(client.margin_calls) == 2
        assert len(client.leverage_calls) == 2

    asyncio.run(runner())


class _HedgeCloseQuantityClient:
    """Client stub returning a fixed hedge position for close orders."""

    def __init__(self, *, quantity: str) -> None:
        self.quantity = quantity
        self.market_calls: list[dict[str, object]] = []
        self.position_requests: list[str | None] = []

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
        return 1_500.0

    async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        return {"step_size": 0.001, "min_qty": 0.001}

    async def get_open_positions(self, symbol: str | None = None) -> dict[str, object]:
        self.position_requests.append(symbol)
        return {
            "code": 0,
            "data": [
                {
                    "symbol": "ETH-USDT",
                    "positionSide": "LONG",
                    "positionAmt": self.quantity,
                }
            ],
        }

    async def place_market(
        self,
        *,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> dict[str, str]:  # noqa: N803
        call = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "positionSide": positionSide,
            "reduceOnly": reduceOnly,
            "closePosition": closePosition,
            "clientOrderId": clientOrderId,
        }
        self.market_calls.append(call)
        return {"status": "ok"}


def test_execute_market_order_uses_remote_quantity_for_hedge_close() -> None:
    """Closing trades without quantity fetch the active position amount."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _HedgeCloseQuantityClient(quantity="0.015")
        state = BotState()
        state.global_trade.hedge_mode = True
        state.global_trade.margin_usdt = 0
        state.global_trade.lev_long = 12
        state.global_trade.lev_short = 12

        await execute_market_order(
            client,
            state=state,
            symbol="ETH-USDT",
            side="SELL",
            quantity=None,
            position_side="LONG",
            reduce_only=True,
        )

        assert client.position_requests == ["ETH-USDT"]
        assert client.market_calls, "Expected close order to be executed"
        call = client.market_calls[0]
        assert call["qty"] == "0.015"
        assert call["positionSide"] == "LONG"
        assert call["reduceOnly"] is False

    asyncio.run(runner())


def test_execute_market_order_errors_when_position_missing() -> None:
    """Closing a hedge position without holdings raises a descriptive error."""

    async def runner() -> None:
        invalidate_symbol_configuration()

        client = _HedgeCloseQuantityClient(quantity="0")
        state = BotState()
        state.global_trade.hedge_mode = True
        state.global_trade.margin_usdt = 0

        with pytest.raises(BingXClientError):
            await execute_market_order(
                client,
                state=state,
                symbol="ETH-USDT",
                side="SELL",
                quantity=None,
                position_side="LONG",
                reduce_only=True,
            )

    asyncio.run(runner())
