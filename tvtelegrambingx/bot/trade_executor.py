from __future__ import annotations

from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations import bingx_client
from tvtelegrambingx.logic_button import compute_button_qty
from tvtelegrambingx.integrations.bingx_settings import (
    ENABLE_SET_LEVERAGE,
    ensure_leverage,
)
from tvtelegrambingx.utils.symbols import norm_symbol

SIDE_MAP = {
    "LONG_BUY": ("BUY", "LONG"),   # Long öffnen
    "LONG_SELL": ("SELL", "LONG"),  # Long schließen
    "SHORT_SELL": ("SELL", "SHORT"),  # Short öffnen
    "SHORT_BUY": ("BUY", "SHORT"),  # Short schließen
}

CFG = ConfigStore()


async def _compute_manual_quantity(symbol: str, position_side: str) -> float:
    """Repliziere die Button-Logik für manuelle Trades."""

    effective = CFG.get_effective(symbol)

    margin_raw = effective.get("margin_usdt")
    if margin_raw is None:
        raise RuntimeError("Kein Margin-Betrag gesetzt. Nutze /margin oder /margin_<symbol>.")

    try:
        margin = float(margin_raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("Ungültiger Margin-Betrag konfiguriert") from exc
    if margin <= 0:
        raise RuntimeError("Margin muss größer als 0 sein")

    leverage_raw = effective.get("leverage", 1)
    try:
        leverage = int(leverage_raw)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("Ungültiger Hebelwert konfiguriert") from exc
    if leverage <= 0:
        raise RuntimeError("Hebel muss größer als 0 sein")

    price = await bingx_client.get_latest_price(symbol)
    if price <= 0:
        raise RuntimeError("Konnte keinen gültigen Preis ermitteln")

    filters = await bingx_client.get_contract_filters(symbol)
    lot_step = float(filters.get("lot_step", 0.001))
    min_qty = float(filters.get("min_qty", lot_step))
    min_notional = float(filters.get("min_notional", 5.0))

    qty = compute_button_qty(
        price=price,
        margin_usdt=margin,
        leverage=leverage,
        lot_step=lot_step,
        min_qty=min_qty,
        min_notional=min_notional,
    )

    if qty <= 0:
        raise RuntimeError("Berechnete Menge ist ungültig")

    return qty


async def execute_trade(symbol: str, action: str) -> bool:
    action = (action or "").upper()
    if action not in SIDE_MAP:
        print(f"[WARN] Unbekannte Aktion: {action}")
        return False

    side, position_side = SIDE_MAP[action]
    symbol = norm_symbol(symbol)

    # Hotfix A: ensure_leverage ist no-op (nur falls Flag gesetzt, aus Rückwärtskompatibilität)
    if action.endswith("BUY") and ENABLE_SET_LEVERAGE:
        await ensure_leverage(symbol, 0, position_side)  # no-op

    print(f"[TRADE] {symbol} → {side}/{position_side}")
    try:
        quantity = await _compute_manual_quantity(symbol, position_side)
        await bingx_client.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            position_side=position_side,
            reduce_only=False,
        )
        return True
    except Exception as exc:  # pragma: no cover - network side effects
        print(f"[ERROR] Trade fehlgeschlagen: {exc}")
        return False
