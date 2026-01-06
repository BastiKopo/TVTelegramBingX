"""Background task that enforces a configurable stop-loss."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from tvtelegrambingx.bot.user_prefs import get_global
from tvtelegrambingx.config import Settings
from tvtelegrambingx.integrations import bingx_account, bingx_client
from tvtelegrambingx.utils.symbols import norm_symbol

LOGGER = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 5.0

_QUANTITY_KEYS: Tuple[str, ...] = (
    "positionAmt",
    "positionAmount",
    "holdVolume",
    "positionVolume",
    "volume",
    "quantity",
    "qty",
)

_ENTRY_PRICE_KEYS: Tuple[str, ...] = (
    "entryPrice",
    "avgPrice",
    "avgEntryPrice",
    "averagePrice",
    "openPrice",
)


@dataclass
class _StopState:
    entry_price: float
    best_price: float
    triggered: bool = False


_STOP_STATE: Dict[Tuple[str, str], _StopState] = {}
_FILTER_CACHE: Dict[str, Tuple[float, float]] = {}


def _parse_chat_id(raw_value: object) -> Optional[int]:
    if raw_value in {None, ""}:
        return None
    try:
        return int(str(raw_value))
    except (TypeError, ValueError):
        LOGGER.warning("Ungültige TELEGRAM_CHAT_ID: %s", raw_value)
        return None


def _first_float(values: Iterable[object]) -> Optional[float]:
    for raw_value in values:
        if raw_value in (None, ""):
            continue
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            continue
    return None


async def _round_quantity(symbol: str, quantity: float) -> float:
    if quantity <= 0:
        return 0.0

    cached = _FILTER_CACHE.get(symbol)
    if cached is None:
        filters = await bingx_client.get_contract_filters(symbol)
        lot_step = _first_float(
            [
                (filters or {}).get("lot_step"),
                (filters or {}).get("stepSize"),
                (filters or {}).get("qty_step"),
                (filters or {}).get("step"),
            ]
        )
        min_qty = _first_float(
            [
                (filters or {}).get("min_qty"),
                (filters or {}).get("minQty"),
                (filters or {}).get("min_quantity"),
            ]
        )
        lot_step = lot_step or 0.001
        min_qty = min_qty or lot_step
        _FILTER_CACHE[symbol] = (lot_step, min_qty)
    else:
        lot_step, min_qty = cached

    lot_step = lot_step or 0.001
    min_qty = min_qty or lot_step

    rounded = math.floor(quantity / lot_step) * lot_step
    rounded = round(rounded, 12)
    if rounded < min_qty:
        return 0.0
    return rounded


async def _notify_stop_loss(
    *,
    settings: Settings,
    symbol: str,
    position_side: str,
    close_qty: float,
    entry_price: float,
    current_price: float,
    loss_percent: float,
) -> None:
    from tvtelegrambingx.bot import telegram_bot

    bot = (
        telegram_bot.APPLICATION.bot
        if telegram_bot.APPLICATION is not None
        else telegram_bot.BOT
    )
    if bot is None:
        LOGGER.debug("Kein Telegram-Bot verfügbar für SL-Benachrichtigung")
        return

    chat_id = _parse_chat_id(settings.telegram_chat_id)
    if chat_id is None:
        LOGGER.debug("Keine TELEGRAM_CHAT_ID konfiguriert – Notification übersprungen")
        return

    direction = "Long" if position_side.upper() == "LONG" else "Short"
    message = (
        "⛔️ Trailing Stop-Loss ausgelöst\n"
        f"Symbol: {symbol}\n"
        f"Richtung: {direction}\n"
        f"Geschlossene Menge: {close_qty:.6f}\n"
        f"Einstieg: {entry_price:.6f}\n"
        f"Aktuell: {current_price:.6f}\n"
        f"Pullback: {loss_percent:.2f}%"
    )

    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception:  # pragma: no cover - network errors
        LOGGER.exception("Senden der SL-Benachrichtigung fehlgeschlagen")


def _update_best_price(
    *, current_price: float, best_price: float, position_side: str
) -> float:
    if current_price <= 0:
        return best_price

    if position_side.upper() == "LONG":
        return max(best_price, current_price)
    return min(best_price, current_price)


def _trailing_pullback_percent(
    *, best_price: float, current_price: float, position_side: str
) -> float:
    if best_price <= 0 or current_price <= 0:
        return 0.0

    if position_side.upper() == "LONG":
        return max(((best_price - current_price) / best_price) * 100.0, 0.0)
    return max(((current_price - best_price) / best_price) * 100.0, 0.0)


async def _maybe_close_position(
    *,
    settings: Settings,
    symbol: str,
    position_side: str,
    quantity: float,
    entry_price: float,
    sl_percent: float,
) -> None:
    key = (symbol, position_side)
    state = _STOP_STATE.get(key)

    if state is None or not math.isclose(state.entry_price, entry_price, rel_tol=1e-9):
        state = _StopState(entry_price=entry_price, best_price=entry_price)
        _STOP_STATE[key] = state

    current_price = await bingx_account.get_mark_price(symbol)
    if current_price <= 0:
        current_price = await bingx_client.get_latest_price(symbol)
    if current_price <= 0:
        LOGGER.debug("Kein Preis für %s verfügbar – SL übersprungen", symbol)
        return

    state.best_price = _update_best_price(
        current_price=current_price,
        best_price=state.best_price,
        position_side=position_side,
    )
    pullback_percent = _trailing_pullback_percent(
        best_price=state.best_price,
        current_price=current_price,
        position_side=position_side,
    )
    if position_side.upper() == "LONG":
        stop_price = state.best_price * (1 - sl_percent / 100.0)
        should_trigger = current_price <= stop_price
    else:
        stop_price = state.best_price * (1 + sl_percent / 100.0)
        should_trigger = current_price >= stop_price

    if pullback_percent < sl_percent or state.triggered or not should_trigger:
        return

    target_qty = await _round_quantity(symbol, abs(quantity))
    if target_qty <= 0:
        LOGGER.debug("Berechnete SL-Menge zu klein für %s", symbol)
        state.triggered = True
        return

    order_side = "SELL" if position_side.upper() == "LONG" else "BUY"

    try:
        await bingx_client.place_order(
            symbol=symbol,
            side=order_side,
            qty=target_qty,
            reduce_only=True,
            position_side=position_side.upper(),
        )
    except Exception:  # pragma: no cover - requires BingX failure scenario
        LOGGER.exception("Stop-Loss-Order fehlgeschlagen für %s", symbol)
        return

    state.triggered = True
    await _notify_stop_loss(
        settings=settings,
        symbol=symbol,
        position_side=position_side,
        close_qty=target_qty,
        entry_price=entry_price,
        current_price=current_price,
        loss_percent=pullback_percent,
    )


async def _process_positions(*, settings: Settings, sl_percent: float) -> None:
    if sl_percent <= 0:
        return

    positions = await bingx_account.get_positions()
    active_keys: set[Tuple[str, str]] = set()

    for entry in positions:
        if not isinstance(entry, dict):
            continue
        raw_symbol = entry.get("symbol") or entry.get("contract")
        if not raw_symbol:
            continue
        symbol = norm_symbol(raw_symbol)
        position_side = (entry.get("positionSide") or entry.get("side") or "").upper()
        if position_side not in {"LONG", "SHORT"}:
            continue

        quantity = _first_float(entry.get(key) for key in _QUANTITY_KEYS)
        if quantity is None or abs(quantity) <= 0:
            _STOP_STATE.pop((symbol, position_side), None)
            continue

        entry_price = _first_float(entry.get(key) for key in _ENTRY_PRICE_KEYS)
        if entry_price is None or entry_price <= 0:
            continue

        active_keys.add((symbol, position_side))
        await _maybe_close_position(
            settings=settings,
            symbol=symbol,
            position_side=position_side,
            quantity=quantity,
            entry_price=entry_price,
            sl_percent=sl_percent,
        )

    for key in list(_STOP_STATE.keys()):
        if key not in active_keys:
            _STOP_STATE.pop(key, None)


async def monitor_stop_loss(settings: Settings) -> None:
    """Continuously watch open positions and close them on loss thresholds."""

    LOGGER.info("Starte Überwachung für Stop-Loss")

    while True:
        try:
            chat_id = _parse_chat_id(settings.telegram_chat_id)
            if chat_id is None:
                await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
                continue

            prefs = get_global(chat_id)
            sl_raw = prefs.get("sl_move_percent")

            try:
                sl_percent = float(sl_raw)
            except (TypeError, ValueError):
                sl_percent = 0.0

            if sl_percent <= 0:
                await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
                continue

            await _process_positions(settings=settings, sl_percent=sl_percent)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Fehler im Stop-Loss-Loop")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
