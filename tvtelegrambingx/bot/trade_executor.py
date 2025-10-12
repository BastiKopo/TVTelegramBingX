from __future__ import annotations

from tvtelegrambingx.integrations.bingx_client import place_order
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
        await place_order(symbol, side, position_side)
        return True
    except Exception as exc:  # pragma: no cover - network side effects
        print(f"[ERROR] Trade fehlgeschlagen: {exc}")
        return False
