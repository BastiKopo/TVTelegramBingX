"""Helpers to emulate the BingX button position sizing logic."""
from __future__ import annotations

from math import floor
from typing import Any, Dict

from tvtelegrambingx.integrations import bingx_client


def compute_button_qty(
    price: float,
    margin_usdt: float,
    leverage: int,
    lot_step: float,
    min_qty: float,
    min_notional: float,
) -> float:
    """Replicate the BingX button quantity calculation."""
    if price <= 0:
        raise ValueError("Ungültiger Preis")
    if lot_step <= 0:
        raise ValueError("Ungültiger lot_step")

    notional_target = max(margin_usdt * leverage, min_notional)
    qty = notional_target / price
    qty = max(min_qty, floor(qty / lot_step) * lot_step)

    if qty * price < min_notional:
        qty = floor((min_notional / price) / lot_step) * lot_step
        qty = max(qty, min_qty)

    return qty


async def place_market_like_button(
    signal: Dict[str, Any],
    eff_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate the order quantity and submit the order like the BingX button."""
    symbol = signal.get("symbol")
    action = signal.get("action", "")
    order_type = (signal.get("order_type") or "MARKET").upper()

    if not symbol:
        raise ValueError("Signal ohne Symbol erhalten")

    action_upper = str(action).upper()
    if "LONG" in action_upper:
        side = "BUY"
        position_side = "LONG"
    elif "SHORT" in action_upper:
        side = "SELL"
        position_side = "SHORT"
    else:
        raise ValueError("Signal muss LONG oder SHORT enthalten")

    if order_type != "MARKET":
        raise ValueError("Nur MARKET im Button-Modus unterstützt")

    mode = str(eff_cfg.get("mode", "button")).lower()
    if mode != "button":
        raise ValueError("Modus ist nicht 'button'. Nutze /mode button.")

    margin_raw = eff_cfg.get("margin_usdt")
    if margin_raw is None:
        raise ValueError("Kein Margin-Betrag gesetzt. Nutze /margin oder /margin_<symbol>.")

    leverage_raw = eff_cfg.get("leverage", 1)
    try:
        leverage = int(leverage_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ungültiger Hebelwert konfiguriert") from exc
    if leverage <= 0:
        raise ValueError("Hebel muss größer als 0 sein")

    try:
        margin = float(margin_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ungültiger Margin-Betrag konfiguriert") from exc
    if margin <= 0:
        raise ValueError("Margin muss größer als 0 sein")

    price = await bingx_client.get_latest_price(symbol)
    filters = await bingx_client.get_contract_filters(symbol)
    qty = compute_button_qty(
        price=price,
        margin_usdt=margin,
        leverage=leverage,
        lot_step=filters["lot_step"],
        min_qty=filters["min_qty"],
        min_notional=filters["min_notional"],
    )

    await bingx_client.set_leverage(symbol=symbol, leverage=leverage, margin_mode="ISOLATED")
    order_result = await bingx_client.place_order(
        symbol=symbol,
        side=side,
        position_side=position_side,
        quantity=qty,
        reduce_only=False,
    )
    return {"quantity": qty, "order": order_result}

