"""Unified order flow bridging manual buttons and TradingView events."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Mapping

from integrations.bingx_contracts import normalize_contract_filters
from integrations.bingx_quote import get_mark_price
from integrations.bingx_settings import ensure_leverage
from integrations.bingx_orders import post_order
from trading.plan import resolve_effective
from trading.qty_calc import qty_from_margin
from utils.symbols import norm_symbol

__all__ = ["configure_adapters", "place_from_event"]

LoadContractFilters = Callable[[str], Awaitable[Mapping[str, Any]]]
FetchPositionQty = Callable[[str, str], Awaitable[str | float | None]]
NowCallable = Callable[[], int]

_load_contract_filters: LoadContractFilters | None = None
_fetch_position_qty: FetchPositionQty | None = None
_now_ms: NowCallable = lambda: int(time.time() * 1000)


def configure_adapters(
    *,
    load_contract_filters: LoadContractFilters | None = None,
    fetch_position_qty: FetchPositionQty | None = None,
    now_ms: NowCallable | None = None,
) -> None:
    """Configure runtime adapters for exchange-specific helpers."""

    global _load_contract_filters, _fetch_position_qty, _now_ms
    if load_contract_filters is not None:
        _load_contract_filters = load_contract_filters
    if fetch_position_qty is not None:
        _fetch_position_qty = fetch_position_qty
    if now_ms is not None:
        _now_ms = now_ms


def map_action(action: str) -> tuple[str, str]:
    token = action.strip().upper()
    if token == "LONG_OPEN":
        return "BUY", "LONG"
    if token == "LONG_CLOSE":
        return "SELL", "LONG"
    if token == "SHORT_OPEN":
        return "SELL", "SHORT"
    if token == "SHORT_CLOSE":
        return "BUY", "SHORT"
    raise ValueError(action)


async def place_from_event(
    chat_id: int,
    symbol: str,
    action: str,
    payload: Mapping[str, Any],
) -> Any:
    """Prepare and submit an order derived from a button or webhook payload."""

    effective = resolve_effective(chat_id, symbol, payload)
    side, position_side = map_action(action)
    symbol_token = norm_symbol(effective["symbol"])

    if action.endswith("OPEN"):
        leverage_value = int(effective.get("lev") or 0)
        if leverage_value <= 0:
            raise ValueError("Leverage fehlt (/leverage setzen).")
        await ensure_leverage(symbol_token, leverage_value, position_side)

    quantity = effective.get("qty")

    if not quantity and action.endswith("OPEN"):
        price = await get_mark_price(symbol_token)
        if _load_contract_filters is None:
            raise RuntimeError("load_contract_filters adapter not configured")
        filters = await _load_contract_filters(symbol_token)
        normalized = normalize_contract_filters(filters)
        quantity = qty_from_margin(
            effective.get("margin_usdt", 0.0),
            int(effective.get("lev") or 0),
            price,
            normalized["stepSize"],
            normalized["minQty"],
        )

    if not quantity and action.endswith("CLOSE"):
        if _fetch_position_qty is None:
            raise RuntimeError("fetch_position_qty adapter not configured")
        quantity = await _fetch_position_qty(symbol_token, position_side)
        if not quantity:
            raise ValueError(f"Keine {position_side}-Position zum Schließen.")

    params = {
        "symbol": symbol_token,
        "side": side,
        "type": "MARKET",
        "quantity": str(quantity),
        "positionSide": position_side,
        "timestamp": _now_ms(),
        "recvWindow": "5000",
    }

    print(
        "[ORDER] eff sym={symbol} side={side} pos={pos} qty={qty} margin={margin} lev={lev}".format(
            symbol=symbol_token,
            side=side,
            pos=position_side,
            qty=quantity,
            margin=effective.get("margin_usdt"),
            lev=effective.get("lev"),
        )
    )

    return await post_order(params)
