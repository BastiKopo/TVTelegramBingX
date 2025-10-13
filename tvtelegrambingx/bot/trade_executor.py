"""Execute trades based on TradingView or manual actions."""
from __future__ import annotations

from tvtelegrambingx.bot.user_prefs import get_global
from tvtelegrambingx.integrations import bingx_account, bingx_client
from tvtelegrambingx.integrations.bingx_settings import ensure_leverage_both
from tvtelegrambingx.logic_button import compute_button_qty
from tvtelegrambingx.utils.symbols import norm_symbol

SIDE_MAP = {
    "LONG_OPEN": ("BUY", "LONG"),
    "LONG_BUY": ("BUY", "LONG"),
    "LONG_CLOSE": ("SELL", "LONG"),
    "LONG_SELL": ("SELL", "LONG"),
    "SHORT_OPEN": ("SELL", "SHORT"),
    "SHORT_SELL": ("SELL", "SHORT"),
    "SHORT_CLOSE": ("BUY", "SHORT"),
    "SHORT_BUY": ("BUY", "SHORT"),
}

OPEN_ACTIONS = {"LONG_OPEN", "LONG_BUY", "SHORT_OPEN", "SHORT_SELL"}


def _resolve_global_settings(chat_id: int) -> tuple[float, int]:
    prefs = get_global(chat_id)
    margin_raw = prefs.get("margin_usdt")
    leverage_raw = prefs.get("leverage")
    if margin_raw in {None, ""} or leverage_raw in {None, ""}:
        raise RuntimeError("Bitte zuerst global /margin <USDT> und /leverage <x> setzen.")
    try:
        margin = float(margin_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ungültiger Margin-Betrag konfiguriert") from exc
    if margin <= 0:
        raise RuntimeError("Margin muss größer als 0 sein")
    try:
        leverage = int(leverage_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ungültiger Hebelwert konfiguriert") from exc
    if leverage <= 0:
        raise RuntimeError("Hebel muss größer als 0 sein")
    return margin, leverage


async def execute_trade(symbol: str, action: str, *, chat_id: int | None = None) -> bool:
    action = (action or "").upper()
    if action not in SIDE_MAP:
        print(f"[WARN] Unbekannte Aktion: {action}")
        return False

    side, position_side = SIDE_MAP[action]
    symbol = norm_symbol(symbol)

    print(f"[TRADE] {symbol} → {side}/{position_side}")

    try:
        if action in OPEN_ACTIONS:
            if chat_id is None:
                raise RuntimeError("chat_id fehlt (für globale Einstellungen).")
            margin, leverage = _resolve_global_settings(chat_id)

            filters = await bingx_client.get_contract_filters(symbol)
            contract = filters.get("raw_contract") if isinstance(filters, dict) else None
            leverage_result = await ensure_leverage_both(
                symbol,
                leverage,
                contract,
                primary_side=position_side,
            )
            effective_leverage = leverage_result.get("leverage", leverage)

            price = await bingx_client.get_latest_price(symbol)
            if price <= 0:
                raise RuntimeError("Konnte keinen gültigen Preis ermitteln")

            lot_step = float(filters.get("lot_step", 0.001))
            min_qty = float(filters.get("min_qty", lot_step))
            min_notional = float(filters.get("min_notional", 5.0))

            quantity = compute_button_qty(
                price=price,
                margin_usdt=margin,
                leverage=effective_leverage,
                lot_step=lot_step,
                min_qty=min_qty,
                min_notional=min_notional,
            )
            if quantity <= 0:
                raise RuntimeError("Berechnete Menge ist ungültig")

            expected_init_margin = (float(quantity) * float(price)) / max(1, effective_leverage)
            print(
                f"[OPEN] {symbol} mark={price} lev={effective_leverage} margin={margin} "
                f"step={lot_step} minQty={min_qty} → qty={quantity} "
                f"(expected_init_margin≈{expected_init_margin:.6f})"
            )

            await bingx_client.place_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                qty=quantity,
            )
        else:
            positions = await bingx_account.get_positions()
            close_qty = 0.0
            for entry in positions:
                if not isinstance(entry, dict):
                    continue
                entry_symbol = entry.get("symbol") or entry.get("contract")
                normalized_entry_symbol = norm_symbol(entry_symbol) if entry_symbol else None
                if normalized_entry_symbol != symbol:
                    continue
                entry_side = (entry.get("positionSide") or entry.get("side") or "").upper()
                if entry_side != position_side:
                    continue

                candidates = (
                    entry.get("positionAmt"),
                    entry.get("positionAmount"),
                    entry.get("holdVolume"),
                    entry.get("positionVolume"),
                    entry.get("volume"),
                    entry.get("quantity"),
                    entry.get("qty"),
                )
                for raw_value in candidates:
                    if raw_value in (None, ""):
                        continue
                    try:
                        close_qty = abs(float(raw_value))
                    except (TypeError, ValueError):
                        continue
                    if close_qty > 0:
                        break
                if close_qty > 0:
                    break

            if close_qty <= 0:
                raise RuntimeError(
                    "Keine offene Position gefunden, die geschlossen werden kann."
                )

            await bingx_client.place_order(
                symbol=symbol,
                side=side,
                position_side=position_side,
                qty=close_qty,
            )
        return True
    except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
        print(f"[ERROR] Trade fehlgeschlagen: {exc}")
        return False
