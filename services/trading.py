"""Shared trading helpers used by manual and automated execution flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from bot.state import BotState
from integrations.bingx_client import BingXClient, BingXClientError, calc_order_qty

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutedOrder:
    """Container holding the prepared order payload and API response."""

    payload: Mapping[str, Any]
    response: Any
    quantity: float
    price: float
    leverage: float


async def execute_market_order(
    client: BingXClient,
    *,
    state: BotState,
    symbol: str,
    side: str,
    quantity: float | None = None,
    margin_usdt: float | None = None,
    margin_mode: str | None = None,
    margin_coin: str | None = None,
    position_side: str | None = None,
    reduce_only: bool = False,
    client_order_id: str | None = None,
) -> ExecutedOrder:
    """Execute a futures market order using the shared configuration from *state*.

    The helper synchronises position mode, margin type and leverage before
    submitting the order to guarantee that manual and automated trades share the
    exact same execution path.
    """

    cfg = state.global_trade
    symbol_token = symbol.strip().upper()
    if not symbol_token:
        raise BingXClientError("Kein Handelssymbol angegeben.")
    side_token = side.strip().upper()
    if side_token not in {"BUY", "SELL"}:
        raise BingXClientError(f"Unsupported order side: {side}")

    margin_mode_value = margin_mode or ("ISOLATED" if cfg.isolated else "CROSSED")
    if isinstance(margin_mode_value, str):
        margin_mode_value = margin_mode_value.strip().upper() or (
            "ISOLATED" if cfg.isolated else "CROSSED"
        )

    margin_coin_value = margin_coin or state.normalised_margin_asset()
    if isinstance(margin_coin_value, str):
        margin_coin_value = margin_coin_value.strip().upper() or state.normalised_margin_asset()

    lev_long = max(1, int(cfg.lev_long or 1))
    lev_short = max(1, int(cfg.lev_short or lev_long))
    leverage_for_side = lev_long if side_token == "BUY" else lev_short

    if isinstance(position_side, str):
        token = position_side.strip().upper()
        position_side = token if token in {"LONG", "SHORT"} else None

    if position_side is None and cfg.hedge_mode:
        position_side = "LONG" if side_token == "BUY" else "SHORT"
    elif not cfg.hedge_mode:
        position_side = None

    budget = margin_usdt if margin_usdt is not None else cfg.margin_usdt
    try:
        margin_budget = float(budget)
    except (TypeError, ValueError):
        margin_budget = cfg.margin_usdt

    if margin_budget <= 0 and quantity is None:
        raise BingXClientError(
            "Autotrade-Konfiguration enthält keinen gültigen Margin-Wert."
        )

    try:
        await client.set_position_mode(cfg.hedge_mode)
    except BingXClientError as exc:
        LOGGER.warning("Failed to update position mode for %s: %s", symbol_token, exc)

    try:
        await client.set_margin_type(
            symbol=symbol_token,
            margin_mode=margin_mode_value,
            margin_coin=margin_coin_value,
        )
    except BingXClientError as exc:
        LOGGER.warning(
            "Failed to synchronise margin configuration for %s: %s",
            symbol_token,
            exc,
        )

    try:
        await client.set_leverage(
            symbol=symbol_token,
            lev_long=lev_long,
            lev_short=lev_short,
            hedge=cfg.hedge_mode,
            margin_coin=margin_coin_value,
        )
    except BingXClientError as exc:
        LOGGER.warning("Failed to synchronise leverage for %s: %s", symbol_token, exc)

    price = await client.get_mark_price(symbol_token)
    filters = await client.get_symbol_filters(symbol_token)
    step_size = float(filters.get("step_size", 0.0))
    min_qty = float(filters.get("min_qty", 0.0))
    min_notional_raw = filters.get("min_notional")
    min_notional = float(min_notional_raw) if min_notional_raw is not None else None

    if step_size <= 0:
        raise BingXClientError(
            f"BingX lieferte keinen gültigen step_size-Filter für {symbol_token}"
        )

    if quantity is None:
        try:
            order_quantity = calc_order_qty(
                price=price,
                margin_usdt=margin_budget,
                leverage=int(leverage_for_side),
                step_size=step_size,
                min_qty=min_qty,
                min_notional=min_notional,
            )
        except ValueError as exc:
            raise BingXClientError(
                f"Ordergröße konnte aus Margin nicht berechnet werden: {exc}"
            ) from exc
    else:
        order_quantity = float(quantity)
        if order_quantity <= 0:
            raise BingXClientError("Positionsgröße muss größer als 0 sein.")

    payload: dict[str, Any] = {
        "symbol": symbol_token,
        "side": side_token,
        "quantity": order_quantity,
        "order_type": "MARKET",
        "leverage": leverage_for_side,
        "margin_mode": margin_mode_value,
        "margin_coin": margin_coin_value,
        "margin_usdt": float(max(margin_budget, 0.0)),
        "position_side": position_side,
        "reduce_only": reduce_only,
        "price": price,
    }
    if client_order_id:
        payload["client_order_id"] = client_order_id

    order_calls = getattr(client, "order_calls", None)
    if isinstance(order_calls, list):
        order_calls.append(dict(payload))

    response = await client.place_futures_market_order(
        symbol=symbol_token,
        side=side_token,
        qty=order_quantity,
        reduce_only=reduce_only,
        position_side=position_side,
        client_order_id=client_order_id,
    )

    return ExecutedOrder(
        payload=payload,
        response=response,
        quantity=order_quantity,
        price=price,
        leverage=float(leverage_for_side),
    )
