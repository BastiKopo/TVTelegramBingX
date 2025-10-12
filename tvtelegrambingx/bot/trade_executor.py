"""Execute trades on BingX."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations import bingx_client
from tvtelegrambingx.logic_button import compute_button_qty

LOGGER = logging.getLogger(__name__)

CONFIG_STORE: Optional[ConfigStore] = None


def configure_store(store: ConfigStore) -> None:
    """Provide the shared configuration store for trade execution."""
    global CONFIG_STORE
    CONFIG_STORE = store


def _derive_order_details(action: str) -> Tuple[str, str, bool]:
    action_upper = action.upper()
    if "LONG" in action_upper:
        position_side = "LONG"
        if any(term in action_upper for term in ("SELL", "CLOSE", "EXIT")):
            side = "SELL"
            is_open = False
        else:
            side = "BUY"
            is_open = True
    elif "SHORT" in action_upper:
        position_side = "SHORT"
        if any(term in action_upper for term in ("BUY", "CLOSE", "EXIT")):
            side = "BUY"
            is_open = False
        else:
            side = "SELL"
            is_open = True
    else:
        raise KeyError(action)

    return side, position_side, is_open


async def _compute_button_quantity(symbol: str, config: ConfigStore, leverage: int) -> float:
    effective = config.get_effective(symbol)
    mode = str(effective.get("mode", "button")).lower()
    if mode != "button":
        raise RuntimeError("Keine Positionsgröße konfiguriert oder im Signal enthalten.")

    margin_raw = effective.get("margin_usdt")
    if margin_raw is None:
        raise RuntimeError("Kein Margin-Betrag gesetzt. Nutze /margin oder /margin_<symbol>.")

    try:
        margin = float(margin_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ungültiger Margin-Betrag konfiguriert.") from exc
    if margin <= 0:
        raise RuntimeError("Margin muss größer als 0 sein.")

    price = await bingx_client.get_latest_price(symbol)
    filters = await bingx_client.get_contract_filters(symbol)
    return compute_button_qty(
        price=price,
        margin_usdt=margin,
        leverage=leverage,
        lot_step=filters["lot_step"],
        min_qty=filters["min_qty"],
        min_notional=filters["min_notional"],
    )


async def execute_trade(
    symbol: str,
    action: str,
    quantity: Optional[float] = None,
) -> Optional[float]:
    """Translate user actions into BingX orders."""
    try:
        side, position_side, is_open = _derive_order_details(action)
    except KeyError:
        LOGGER.warning("Unknown trade action received: %s", action)
        return None

    final_quantity = quantity
    if final_quantity is None:
        leverage_config = 1
        if CONFIG_STORE is not None:
            effective = CONFIG_STORE.get_effective(symbol)
            try:
                leverage_config = int(effective.get("leverage", 1))
            except (TypeError, ValueError):
                leverage_config = 1
        else:
            effective = {}

        if is_open:
            if CONFIG_STORE is None:
                raise RuntimeError("Keine Positionsgröße konfiguriert oder im Signal enthalten.")
            final_quantity = await _compute_button_quantity(
                symbol=symbol,
                config=CONFIG_STORE,
                leverage=max(leverage_config, 1),
            )
            await bingx_client.set_leverage(
                symbol=symbol,
                leverage=max(leverage_config, 1),
                margin_mode="ISOLATED",
            )
        else:
            raise RuntimeError("Keine Positionsgröße konfiguriert oder im Signal enthalten.")

    LOGGER.info(
        "Submitting BingX order: symbol=%s side=%s position=%s quantity=%s",
        symbol,
        side,
        position_side,
        final_quantity,
    )

    try:
        await bingx_client.place_order(
            symbol=symbol,
            side=side,
            quantity=final_quantity,
            reduce_only=False if position_side else not is_open,
            position_side=position_side,
        )
    except Exception as exc:  # pragma: no cover - defensive logging only
        LOGGER.exception("Trade execution failed: symbol=%s action=%s", symbol, action)
        raise exc

    return final_quantity
