"""Background task to enforce dynamic take-profit rules."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional, Sequence, Tuple

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
class _TriggerState:
    entry_price: float
    triggered_levels: set[int] = field(default_factory=set)


_TRIGGER_STATE: Dict[Tuple[str, str], _TriggerState] = {}
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


async def _notify_dynamic_tp(
    *,
    settings: Settings,
    symbol: str,
    position_side: str,
    sell_qty: float,
    entry_price: float,
    current_price: float,
    change_percent: float,
    sell_percent: float,
    trigger_level: int,
) -> None:
    from tvtelegrambingx.bot import telegram_bot

    bot = (
        telegram_bot.APPLICATION.bot
        if telegram_bot.APPLICATION is not None
        else telegram_bot.BOT
    )
    if bot is None:
        LOGGER.debug("Kein Telegram-Bot verfügbar für TP-Benachrichtigung")
        return

    chat_id = _parse_chat_id(settings.telegram_chat_id)
    if chat_id is None:
        LOGGER.debug("Keine TELEGRAM_CHAT_ID konfiguriert – Notification übersprungen")
        return

    direction = "Long" if position_side.upper() == "LONG" else "Short"
    message = (
        "🎯 Dynamischer TP ausgelöst\n"
        f"Symbol: {symbol}\n"
        f"Richtung: {direction}\n"
        f"TP-Stufe: TP{trigger_level}\n"
        f"Verkaufte Menge: {sell_qty:.6f}\n"
        f"Einstieg: {entry_price:.6f}\n"
        f"Aktuell: {current_price:.6f}\n"
        f"Bewegung: {change_percent:.2f}%\n"
        f"Teilverkauf: {sell_percent:.2f}%"
    )

    try:
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception:  # pragma: no cover - network errors
        LOGGER.exception("Senden der TP-Benachrichtigung fehlgeschlagen")


def _price_change_percent(
    *, entry_price: float, current_price: float, position_side: str
) -> float:
    if entry_price <= 0 or current_price <= 0:
        return 0.0

    if position_side.upper() == "LONG":
        return ((current_price - entry_price) / entry_price) * 100.0
    return ((entry_price - current_price) / entry_price) * 100.0


async def _maybe_reduce_position(
    *,
    settings: Settings,
    symbol: str,
    position_side: str,
    quantity: float,
    entry_price: float,
    triggers: Sequence[Tuple[int, float, float]],
) -> None:
    key = (symbol, position_side)
    state = _TRIGGER_STATE.get(key)

    if state is None or not math.isclose(state.entry_price, entry_price, rel_tol=1e-9):
        state = _TriggerState(entry_price=entry_price)
        _TRIGGER_STATE[key] = state

    current_price = await bingx_account.get_mark_price(symbol)
    if current_price <= 0:
        current_price = await bingx_client.get_latest_price(symbol)
    if current_price <= 0:
        LOGGER.debug("Kein Preis für %s verfügbar – dynamischer TP übersprungen", symbol)
        return

    change_percent = _price_change_percent(
        entry_price=entry_price,
        current_price=current_price,
        position_side=position_side,
    )

    for trigger_level, move_percent, sell_percent in triggers:
        if trigger_level in state.triggered_levels:
            continue
        if change_percent < move_percent:
            continue

        target_qty = abs(quantity) * min(sell_percent, 100.0) / 100.0
        target_qty = await _round_quantity(symbol, target_qty)
        if target_qty <= 0:
            LOGGER.debug("Berechnete Verkaufsmenge zu klein für %s", symbol)
            state.triggered_levels.add(trigger_level)
            continue

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
            LOGGER.exception("Dynamischer TP-Order fehlgeschlagen für %s", symbol)
            continue

        state.triggered_levels.add(trigger_level)
        await _notify_dynamic_tp(
            settings=settings,
            symbol=symbol,
            position_side=position_side,
            sell_qty=target_qty,
            entry_price=entry_price,
            current_price=current_price,
            change_percent=change_percent,
            sell_percent=min(sell_percent, 100.0),
            trigger_level=trigger_level,
        )


async def _process_positions(
    *,
    settings: Settings,
    triggers: Sequence[Tuple[int, float, float]],
) -> None:
    if not triggers:
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
            _TRIGGER_STATE.pop((symbol, position_side), None)
            continue

        entry_price = _first_float(entry.get(key) for key in _ENTRY_PRICE_KEYS)
        if entry_price is None or entry_price <= 0:
            continue

        active_keys.add((symbol, position_side))
        await _maybe_reduce_position(
            settings=settings,
            symbol=symbol,
            position_side=position_side,
            quantity=quantity,
            entry_price=entry_price,
            triggers=triggers,
        )

    for key in list(_TRIGGER_STATE.keys()):
        if key not in active_keys:
            _TRIGGER_STATE.pop(key, None)


async def monitor_dynamic_tp(settings: Settings) -> None:
    """Continuously watch open positions and apply dynamic TP rules."""

    LOGGER.info("Starte Überwachung für dynamischen Take-Profit")

    while True:
        try:
            chat_id = _parse_chat_id(settings.telegram_chat_id)
            if chat_id is None:
                await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
                continue

            prefs = get_global(chat_id)
            move_raw = prefs.get("tp_move_percent")
            sell_raw = prefs.get("tp_sell_percent")
            move2_raw = prefs.get("tp2_move_percent")
            sell2_raw = prefs.get("tp2_sell_percent")
            move3_raw = prefs.get("tp3_move_percent")
            sell3_raw = prefs.get("tp3_sell_percent")

            try:
                move_percent = float(move_raw)
            except (TypeError, ValueError):
                move_percent = 0.0

            try:
                sell_percent = float(sell_raw)
            except (TypeError, ValueError):
                sell_percent = 0.0

            try:
                move2_percent = float(move2_raw)
            except (TypeError, ValueError):
                move2_percent = 0.0

            try:
                sell2_percent = float(sell2_raw)
            except (TypeError, ValueError):
                sell2_percent = 0.0

            try:
                move3_percent = float(move3_raw)
            except (TypeError, ValueError):
                move3_percent = 0.0

            try:
                sell3_percent = float(sell3_raw)
            except (TypeError, ValueError):
                sell3_percent = 0.0

            triggers = []
            if move_percent > 0 and sell_percent > 0:
                triggers.append((1, move_percent, sell_percent))
            if move2_percent > 0 and sell2_percent > 0:
                triggers.append((2, move2_percent, sell2_percent))
            if move3_percent > 0 and sell3_percent > 0:
                triggers.append((3, move3_percent, sell3_percent))

            triggers.sort(key=lambda item: item[1])

            if not triggers:
                await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
                continue

            await _process_positions(
                settings=settings,
                triggers=triggers,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Fehler im dynamischen TP-Loop")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
