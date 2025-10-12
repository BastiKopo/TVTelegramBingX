"""Helpers to emulate the BingX button position sizing logic."""
from __future__ import annotations

from math import floor
from typing import Any, Dict

from tvtelegrambingx.integrations import bingx_client
from tvtelegrambingx.integrations.bingx_settings import ensure_leverage_both


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
    lot_step = float(filters.get("lot_step", 0.001))
    min_qty = float(filters.get("min_qty", lot_step))
    min_notional = float(filters.get("min_notional", 5.0))

    lev_info = await ensure_leverage_both(
        symbol=symbol,
        leverage=leverage,
        sym_filters=filters.get("raw_contract") if isinstance(filters, dict) else None,
    )
    effective_leverage = lev_info.get("leverage", leverage)
    qty = compute_button_qty(
        price=price,
        margin_usdt=margin,
        leverage=effective_leverage,
        lot_step=lot_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )

    side_info = lev_info.get(position_side.upper(), {}) if isinstance(lev_info, dict) else {}
    data = side_info.get("data") if isinstance(side_info, dict) else {}
    available_value = None
    if isinstance(data, dict):
        try:
            if position_side == "LONG":
                available_value = float(data.get("availableLongVal"))
            else:
                available_value = float(data.get("availableShortVal"))
        except (TypeError, ValueError):
            available_value = None

    notional = qty * price
    if available_value is not None and notional > available_value:
        capped_qty = max(min_qty, available_value / price)
        capped_qty = max(min_qty, floor(capped_qty / lot_step) * lot_step)
        if capped_qty * price < min_notional:
            raise RuntimeError(
                f"Insufficient margin: benötigte Notional {notional:.2f} > verfügbar {available_value:.2f}"
            )
        qty = capped_qty

    order_result = await bingx_client.place_order(
        symbol=symbol,
        side=side,
        quantity=qty,
        position_side=position_side,
    )
    return {"quantity": qty, "order": order_result}

