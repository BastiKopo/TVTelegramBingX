"""Telegram bot entry point for TVTelegramBingX."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import re
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Final
import sys

from config import Settings, get_settings
from integrations.bingx_client import BingXClient, BingXClientError
from integrations.telegram_format import build_signal_message
from services.idempotency import generate_client_order_id
from services.order_mapping import map_action
from services.symbols import SymbolValidationError, normalize_symbol
from services.trading import invalidate_symbol_configuration
from webhook.dispatcher import get_alert_queue, place_signal_order

from .state import (
    BotState,
    export_state_snapshot,
    load_state,
    load_state_snapshot,
    save_state,
    STATE_EXPORT_FILE,
)

LOGGER: Final = logging.getLogger(__name__)

import telegram as _telegram_module
from telegram import BotCommand, ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

STATE_FILE: Final = Path("bot_state.json")
STATE_SNAPSHOT_FILE: Final = STATE_EXPORT_FILE
MAIN_KEYBOARD: Final = ReplyKeyboardMarkup(
    [
        ["/start", "/stop", "/status"],
        ["/report", "/positions", "/sync"],
    ],
    resize_keyboard=True,
)

MANUAL_ALERT_HISTORY_LIMIT: Final = 50
GLOBAL_MARGIN_TOO_SMALL_MESSAGE: Final = (
    "Global Margin zu klein für aktuellen Preis/Leverage/StepSize."
)

_InlineKeyboardButtonType = getattr(_telegram_module, "InlineKeyboardButton", None)
if _InlineKeyboardButtonType is None:

    class InlineKeyboardButton:
        """Fallback InlineKeyboardButton used during tests without telegram library."""

        def __init__(self, text: str, callback_data: str | None = None, **kwargs: Any) -> None:
            self.text = text
            self.callback_data = callback_data
            self.kwargs = kwargs

else:
    InlineKeyboardButton = _InlineKeyboardButtonType  # type: ignore[assignment]

_InlineKeyboardMarkupType = getattr(_telegram_module, "InlineKeyboardMarkup", None)
if _InlineKeyboardMarkupType is None:

    class InlineKeyboardMarkup:
        """Fallback InlineKeyboardMarkup used during tests without telegram library."""

        def __init__(self, inline_keyboard: Sequence[Sequence[InlineKeyboardButton]]) -> None:
            self.inline_keyboard = inline_keyboard

else:
    InlineKeyboardMarkup = _InlineKeyboardMarkupType  # type: ignore[assignment]

_telegram_ext_module = sys.modules.get("telegram.ext")
_CallbackQueryHandlerType = (
    getattr(_telegram_ext_module, "CallbackQueryHandler", None)
    if _telegram_ext_module is not None
    else None
)
if _CallbackQueryHandlerType is None:

    class CallbackQueryHandler:
        """Fallback CallbackQueryHandler used during tests without telegram library."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

else:
    CallbackQueryHandler = _CallbackQueryHandlerType  # type: ignore[assignment]


def _state_from_context(context: ContextTypes.DEFAULT_TYPE) -> BotState:
    """Return the shared :class:`BotState` instance."""

    state = context.application.bot_data.get("state") if context.application else None
    if isinstance(state, BotState):
        return state
    new_state = BotState()
    if context.application:
        context.application.bot_data["state"] = new_state
    return new_state


def _persist_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the current bot state to disk."""

    if not context.application:
        return
    state = context.application.bot_data.get("state")
    state_file = context.application.bot_data.get("state_file", STATE_FILE)
    if isinstance(state, BotState):
        try:
            save_state(Path(state_file), state)
        except Exception:  # pragma: no cover - filesystem issues are logged only
            LOGGER.exception("Failed to persist bot state to %s", state_file)
        else:
            try:
                export_state_snapshot(state)
            except Exception:  # pragma: no cover - filesystem issues are logged only
                LOGGER.exception("Failed to persist state snapshot to %s", STATE_SNAPSHOT_FILE)


def _apply_settings_defaults_to_state(state: BotState, settings: Settings) -> None:
    """Initialise ``state`` with global defaults from ``settings``."""

    state.margin_mode = settings.default_margin_mode.lower()
    state.global_trade.isolated = settings.default_margin_mode.lower() != "cross"
    state.global_trade.hedge_mode = settings.position_mode == "hedge"
    state.set_margin(settings.default_margin_usdt)
    state.set_leverage(
        lev_long=settings.default_leverage,
        lev_short=settings.default_leverage,
    )
    state.leverage = float(settings.default_leverage)
    state.global_trade.set_time_in_force(settings.default_time_in_force)
    if not state.margin_asset:
        state.margin_asset = "USDT"


def _resolve_state_for_order(
    application: Application,
) -> tuple[BotState | None, Mapping[str, Any] | None]:
    """Return the merged bot state and optional snapshot used for trades."""

    state_in_memory = application.bot_data.get("state")
    state_file = Path(application.bot_data.get("state_file", STATE_FILE))

    persisted_state = load_state(state_file)
    if not isinstance(state_in_memory, BotState):
        state_in_memory = persisted_state
        if isinstance(state_in_memory, BotState):
            application.bot_data["state"] = state_in_memory

    merged_state_data: dict[str, Any] = {}

    if isinstance(state_in_memory, BotState):
        try:
            merged_state_data.update(state_in_memory.to_dict())
        except Exception:
            merged_state_data.clear()

    if isinstance(persisted_state, BotState):
        try:
            merged_state_data.update(persisted_state.to_dict())
        except Exception:
            pass

    snapshot = load_state_snapshot()
    if snapshot:
        try:
            merged_state_data.update(snapshot)
        except Exception:
            snapshot = None

    state_for_order: BotState | None
    if merged_state_data:
        try:
            state_for_order = BotState.from_mapping(merged_state_data)
        except Exception:
            state_for_order = None
    else:
        state_for_order = state_in_memory if isinstance(state_in_memory, BotState) else persisted_state

    if not isinstance(state_for_order, BotState):
        return None, snapshot
    return state_for_order, snapshot


def _reschedule_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reschedule the daily report job after a state change."""

    if not context.application:
        return

    settings = _get_settings(context)
    state = context.application.bot_data.get("state")
    if isinstance(state, BotState) and settings:
        _schedule_daily_report(context.application, settings, state)


def _parse_time(value: str) -> time | None:
    """Return a :class:`datetime.time` from ``HH:MM`` strings."""

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        return None
    return parsed.time()


class CommandUsageError(ValueError):
    """Exception raised when a Telegram command receives invalid arguments."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class ManualOrderRequest:
    symbol: str
    quantity: float | None
    margin: float | None
    leverage: int | None
    limit_price: float | None
    time_in_force: str | None
    reduce_only: bool | None
    direction: str | None = None
    client_order_id: str | None = None


@dataclass(slots=True)
class QuickTradeArguments:
    """Container for parsed shortcut trade command options."""

    symbol: str
    quantity: float | None
    limit_price: float | None
    time_in_force: str | None
    client_order_id: str | None


def _normalise_symbol(value: str) -> str:
    """Return an uppercase trading symbol without broker prefixes."""

    text = value.strip()
    if not text:
        return ""
    try:
        return normalize_symbol(text)
    except SymbolValidationError:
        token = text.upper()
        if ":" in token:
            token = token.rsplit(":", 1)[-1]
        return token


def _looks_like_symbol(value: str) -> bool:
    """Heuristically decide whether *value* represents a trading symbol."""

    candidate = value.strip().upper()
    if not candidate:
        return False

    has_alpha = any(char.isalpha() for char in candidate)
    has_digit = any(char.isdigit() for char in candidate)

    if ":" in candidate or "-" in candidate:
        return True
    if has_alpha and has_digit:
        return True
    if has_alpha and len(candidate) > 4:
        return True
    return False


MARGIN_USAGE = (
    "Nutzung: /margin [Symbol] [Coin] [cross|isolated]\n"
    "Beispiel: /margin BTCUSDT USDT isolated"
)


LEVERAGE_USAGE = (
    "Nutzung: /leverage [Symbol] <Wert> [cross|isolated] [Coin]\n"
    "Beispiel: /leverage BTCUSDT 20 isolated USDT"
)


def _normalise_margin_mode_token(value: str | None) -> str | None:
    """Return ``cross``/``isolated`` for accepted *value* tokens."""

    if not value:
        return None

    lowered = value.strip().lower()
    if not lowered:
        return None
    if lowered.startswith("isol"):
        return "isolated"
    if lowered.startswith("cross"):
        return "cross"
    return None


def _parse_float_token(value: str) -> float | None:
    """Return a float for *value* if possible."""

    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def _parse_int_token(value: str) -> int | None:
    """Return an integer for *value* ignoring a trailing ``x`` token."""

    cleaned = value.strip().lower().rstrip("x")
    if not cleaned:
        return None
    try:
        parsed = int(float(cleaned))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _coerce_float_value(value: Any) -> float | None:
    """Best-effort conversion of arbitrary payload values into floats."""

    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _parse_float_token(value)
    return None


def _parse_margin_command_args(
    args: Sequence[str],
    *,
    default_mode: str | None = None,
    default_coin: str | None = None,
) -> tuple[str | None, bool, str, str | None]:
    """Return ``(symbol, symbol_provided, margin_mode, margin_coin)`` for /margin."""

    tokens = [str(arg).strip() for arg in args if str(arg).strip()]
    if not tokens:
        raise CommandUsageError(
            "Bitte gib cross oder isolated an.\n" + MARGIN_USAGE
        )

    allowed_modes = {"cross", "crossed", "isolated", "isol"}
    symbol: str | None = None
    symbol_was_provided = False

    margin_mode = _normalise_margin_mode_token(default_mode)
    margin_coin = (default_coin or "").strip().upper() or None

    working = list(tokens)

    for index, token in enumerate(list(working)):
        lowered = token.lower()
        if lowered in allowed_modes:
            continue
        if _looks_like_symbol(token):
            symbol = _normalise_symbol(token)
            symbol_was_provided = True
            working.pop(index)
            break

    mode_index = next((i for i, token in enumerate(working) if token.lower() in allowed_modes), None)
    if mode_index is not None:
        margin_mode = _normalise_margin_mode_token(working.pop(mode_index))

    if working:
        margin_coin = working.pop(0).upper()

    if working:
        raise CommandUsageError(
            "Zu viele Argumente übergeben.\n" + MARGIN_USAGE
        )

    if margin_mode is None:
        raise CommandUsageError(
            "Bitte gib cross oder isolated an.\n" + MARGIN_USAGE
        )

    return symbol, symbol_was_provided, margin_mode, margin_coin


def _parse_leverage_command_args(
    args: Sequence[str],
    *,
    default_mode: str | None = None,
    default_coin: str | None = None,
) -> tuple[str | None, bool, float, str | None, str]:
    """Return ``(symbol, symbol_provided, leverage, margin_coin, margin_mode)`` for /leverage."""

    tokens = [str(arg).strip() for arg in args if str(arg).strip()]
    if not tokens:
        raise CommandUsageError(
            "Bitte gib einen numerischen Leverage-Wert an.\n" + LEVERAGE_USAGE
        )

    def _parse_leverage(token: str) -> float | None:
        cleaned = token.lower().rstrip("x")
        try:
            return float(cleaned)
        except ValueError:
            return None

    working = list(tokens)
    leverage_index = next((i for i, token in enumerate(working) if _parse_leverage(token) is not None), None)
    if leverage_index is None:
        raise CommandUsageError(
            "Bitte gib einen numerischen Leverage-Wert an.\n" + LEVERAGE_USAGE
        )

    leverage_value = _parse_leverage(working.pop(leverage_index))
    assert leverage_value is not None

    if leverage_value <= 0:
        raise CommandUsageError("Leverage muss größer als 0 sein.\n" + LEVERAGE_USAGE)

    symbol: str | None = None
    symbol_was_provided = False

    allowed_modes = {"cross", "crossed", "isolated", "isol"}
    margin_mode = _normalise_margin_mode_token(default_mode)
    margin_coin = (default_coin or "").strip().upper() or None

    for index, token in enumerate(working):
        lowered = token.lower()
        if lowered in allowed_modes:
            continue
        if _looks_like_symbol(token):
            symbol = _normalise_symbol(token)
            symbol_was_provided = True
            working.pop(index)
            break

    mode_index = next((i for i, token in enumerate(working) if token.lower() in allowed_modes), None)
    if mode_index is not None:
        margin_mode = _normalise_margin_mode_token(working.pop(mode_index))

    if working:
        margin_coin = working.pop(0).upper()

    if working:
        raise CommandUsageError(
            "Zu viele Argumente übergeben.\n" + LEVERAGE_USAGE
        )

    if margin_mode is None:
        raise CommandUsageError(
            "Bitte gib cross oder isolated an.\n" + LEVERAGE_USAGE
        )

    return symbol, symbol_was_provided, leverage_value, margin_coin, margin_mode


def _parse_manual_order_args(
    args: Sequence[str],
    *,
    require_direction: bool = True,
) -> ManualOrderRequest:
    tokens = [str(token).strip() for token in args if str(token).strip()]
    if not tokens:
        raise CommandUsageError(
            "Nutzung: /buy <Symbol> <Menge> <LONG|SHORT>"
            if require_direction
            else "Nutzung: /open <Symbol> <Menge>"
        )

    options: dict[str, str] = {}
    positional: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            key = token[2:].lower()
            if key not in {"margin", "qty", "lev", "limit", "tif", "reduce-only", "clid"}:
                raise CommandUsageError(f"Unbekannte Option {token}.")
            if i + 1 >= len(tokens):
                raise CommandUsageError(f"Option {token} benötigt einen Wert.")
            value = tokens[i + 1]
            if not value or value.startswith("--"):
                raise CommandUsageError(f"Option {token} benötigt einen Wert.")
            options[key] = value
            i += 2
            continue
        positional.append(token)
        i += 1

    direction: str | None = None
    core_tokens = positional
    if require_direction:
        if not positional:
            raise CommandUsageError("Bitte gib Symbol, Menge und Richtung an.")
        direction_token = positional[-1].strip().upper()
        if direction_token not in {"LONG", "SHORT"}:
            raise CommandUsageError("Richtung muss LONG oder SHORT sein.")
        direction = direction_token
        core_tokens = positional[:-1]

    if not core_tokens:
        raise CommandUsageError("Bitte gib ein Handelssymbol an.")

    symbol = core_tokens[0]
    remaining = core_tokens[1:]
    if len(remaining) > 1:
        raise CommandUsageError("Zu viele Argumente übergeben.")

    margin_value: float | None
    if "margin" in options:
        margin_value = _coerce_float_value(options["margin"])
        if margin_value is None:
            raise CommandUsageError("Margin-Wert muss numerisch sein.")
        if margin_value <= 0:
            raise CommandUsageError("Margin-Wert muss größer als 0 sein.")
    else:
        margin_value = None

    qty_option = options.get("qty")
    qty_value = _coerce_float_value(qty_option) if qty_option is not None else None
    if qty_option is not None and qty_value is None:
        raise CommandUsageError("Positionsgröße muss numerisch sein.")

    positional_qty = None
    if remaining:
        positional_qty = _coerce_float_value(remaining[0])
        if positional_qty is None:
            raise CommandUsageError("Bitte gib eine numerische Positionsgröße an.")

    quantity_value = qty_value if qty_value is not None else positional_qty
    if quantity_value is not None and quantity_value <= 0:
        raise CommandUsageError("Positionsgröße muss größer als 0 sein.")

    lev_option = options.get("lev")
    leverage_value = _parse_int_token(lev_option) if lev_option is not None else None
    if lev_option is not None and leverage_value is None:
        raise CommandUsageError("Ungültiger Wert für --lev.")

    limit_price: float | None = None
    if "limit" in options:
        limit_price = _coerce_float_value(options["limit"])
        if limit_price is None:
            raise CommandUsageError("Limit-Preis muss numerisch sein.")
        if limit_price <= 0:
            raise CommandUsageError("Limit-Preis muss größer als 0 sein.")

    tif_value: str | None = None
    tif_option = options.get("tif")
    if tif_option:
        tif_token = tif_option.strip().upper()
        if tif_token not in {"GTC", "IOC", "FOK"}:
            raise CommandUsageError("Ungültiges TIF. Erlaubt: GTC, IOC, FOK.")
        tif_value = tif_token

    reduce_only_option = options.get("reduce-only")
    reduce_only_value: bool | None
    if reduce_only_option is not None:
        reduce_only_token = _bool_from_value(reduce_only_option)
        if reduce_only_token is None:
            raise CommandUsageError("Ungültiger Wert für --reduce-only. Verwende 0 oder 1.")
        reduce_only_value = reduce_only_token
    else:
        reduce_only_value = None

    if quantity_value is None and margin_value is None:
        raise CommandUsageError("Bitte gib --qty oder --margin an.")

    client_order_id = None
    clid_option = options.get("clid")
    if clid_option is not None:
        client_order_id = clid_option.strip() or None

    return ManualOrderRequest(
        symbol=symbol,
        quantity=quantity_value,
        margin=margin_value,
        leverage=leverage_value,
        limit_price=limit_price,
        time_in_force=tif_value,
        reduce_only=reduce_only_value,
        direction=direction,
        client_order_id=client_order_id,
    )


def _parse_quick_trade_arguments(
    tokens: Sequence[str],
    *,
    default_tif: str,
) -> QuickTradeArguments:
    """Parse shortcut trade arguments for manual open/close commands."""

    positional: list[str] = []
    options: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            key = token[2:].strip().lower()
            if key not in {"qty", "limit", "tif", "clid"}:
                raise CommandUsageError(f"Unbekannte Option {token}.")
            if i + 1 >= len(tokens):
                raise CommandUsageError(f"Option {token} benötigt einen Wert.")
            value = tokens[i + 1]
            if not value or value.startswith("--"):
                raise CommandUsageError(f"Option {token} benötigt einen Wert.")
            options[key] = value
            i += 2
            continue
        positional.append(token)
        i += 1

    if not positional:
        raise CommandUsageError("Bitte Symbol angeben (z. B. BTCUSDT).")
    if len(positional) > 1:
        raise CommandUsageError("Bitte gib genau ein Handelssymbol an.")

    symbol = positional[0]

    quantity_value: float | None = None
    qty_option = options.get("qty")
    if qty_option is not None:
        quantity_value = _coerce_float_value(qty_option)
        if quantity_value is None:
            raise CommandUsageError("Positionsgröße muss numerisch sein.")
        if quantity_value <= 0:
            raise CommandUsageError("Positionsgröße muss größer als 0 sein.")

    limit_price: float | None = None
    limit_option = options.get("limit")
    if limit_option is not None:
        limit_price = _coerce_float_value(limit_option)
        if limit_price is None:
            raise CommandUsageError("Limit-Preis muss numerisch sein.")
        if limit_price <= 0:
            raise CommandUsageError("Limit-Preis muss größer als 0 sein.")

    tif_value: str | None = None
    tif_option = options.get("tif")
    if tif_option is not None:
        tif_candidate = tif_option.strip().upper()
        if tif_candidate not in {"GTC", "IOC", "FOK"}:
            raise CommandUsageError("Ungültiges TIF. Erlaubt: GTC, IOC, FOK.")
        tif_value = tif_candidate
    elif limit_price is not None:
        fallback = default_tif.strip().upper() if default_tif else "GTC"
        tif_value = fallback if fallback in {"GTC", "IOC", "FOK"} else "GTC"

    client_order_id = None
    clid_option = options.get("clid")
    if clid_option is not None:
        client_order_id = clid_option.strip() or None

    return QuickTradeArguments(
        symbol=symbol,
        quantity=quantity_value,
        limit_price=limit_price,
        time_in_force=tif_value,
        client_order_id=client_order_id,
    )


def _quick_trade_request_from_args(
    state: BotState,
    trade: QuickTradeArguments,
    *,
    reduce_only: bool,
) -> ManualOrderRequest:
    """Return a :class:`ManualOrderRequest` built from parsed quick trade data."""

    tif_value = trade.time_in_force
    if trade.limit_price is not None and tif_value is None:
        tif_value = state.global_trade.normalised_time_in_force()

    return ManualOrderRequest(
        symbol=trade.symbol,
        quantity=trade.quantity,
        margin=None,
        leverage=None,
        limit_price=trade.limit_price,
        time_in_force=tif_value,
        reduce_only=reduce_only,
        client_order_id=trade.client_order_id,
    )


def _map_known_error_message(error: Exception) -> str | None:
    """Translate known BingX error payloads into user friendly messages."""

    text = str(error)
    lowered = text.lower()
    if "quantity rounded to zero" in lowered or "quantity below minimum" in lowered:
        return GLOBAL_MARGIN_TOO_SMALL_MESSAGE
    if "no position to close" in lowered or "keine passende position" in lowered or "101205" in lowered:
        return "Keine passende Position zu schließen."
    if "109414" in lowered:
        return "Hedge-Mode aktiv – bitte LONG/SHORT verwenden."
    return None


def _resolve_manual_action(kind: str, direction: str) -> str:
    mapping = {
        ("open", "LONG"): "LONG_OPEN",
        ("open", "SHORT"): "SHORT_OPEN",
        ("close", "LONG"): "LONG_CLOSE",
        ("close", "SHORT"): "SHORT_CLOSE",
    }
    try:
        return mapping[(kind, direction.upper())]
    except KeyError as exc:
        raise CommandUsageError("Unbekannte Richtung für den Befehl.") from exc


def _format_futures_settings_summary(state: BotState) -> str:
    """Return a summary of the stored global futures configuration."""

    lines = ["⚙️ Globale Futures-Einstellungen:"]

    margin_mode = state.normalised_margin_mode()
    margin_coin = state.normalised_margin_asset()
    lines.append(f"• Margin-Modus: {margin_mode}")
    if margin_coin:
        lines.append(f"• Margin-Coin: {margin_coin}")

    leverage_value = state.leverage
    lines.append(f"• Leverage: {leverage_value:g}x")

    lines.append("")
    lines.append(
        "Diese Werte werden für alle Futures-Trades verwendet. Passe sie mit /margin, /lev, /mode, /mgnmode oder /tif an."
    )

    return "\n".join(lines)


def _format_global_trade_summary(state: BotState) -> str:
    """Return a formatted summary of the global trade configuration."""

    cfg = state.global_trade
    isolated = "Ja" if cfg.isolated else "Nein"
    hedge = "Ja" if cfg.hedge_mode else "Nein"

    lines = ["Global:"]

    lines.append(f"- Margin: {cfg.margin_usdt:.2f} USDT")

    if cfg.lev_long == cfg.lev_short:
        lines.append(f"- Leverage: {cfg.lev_long}x")
    else:
        lines.append(f"- Leverage Long: {cfg.lev_long}x")
        lines.append(f"- Leverage Short: {cfg.lev_short}x")

    lines.append(f"- Isolated: {isolated}")
    lines.append(f"- Hedge-Mode: {hedge}")
    lines.append(f"- Default TIF: {cfg.normalised_time_in_force()}")

    return "\n".join(lines)


def _extract_symbol_from_alert(alert: Mapping[str, Any]) -> str | None:
    """Return the trading symbol encoded in a TradingView alert payload."""

    if not isinstance(alert, Mapping):
        return None

    strategy_data = alert.get("strategy")
    strategy = strategy_data if isinstance(strategy_data, Mapping) else {}

    for candidate in (
        alert.get("symbol"),
        alert.get("ticker"),
        alert.get("pair"),
        alert.get("market"),
        strategy.get("market"),
        strategy.get("symbol"),
    ):
        if not candidate:
            continue
        symbol = _normalise_symbol(str(candidate))
        if symbol:
            return symbol
    return None


def _store_last_symbol(application: Application, symbol: str) -> None:
    """Persist the most recent trading symbol for later reuse."""

    trimmed = _normalise_symbol(symbol)
    if not trimmed:
        return

    state = application.bot_data.get("state")
    if not isinstance(state, BotState):
        return

    if state.last_symbol == trimmed:
        return

    state.last_symbol = trimmed

    state_file = Path(application.bot_data.get("state_file", STATE_FILE))
    try:
        save_state(state_file, state)
    except Exception:  # pragma: no cover - filesystem issues are logged only
        LOGGER.exception("Failed to persist updated symbol to %s", state_file)
    else:
        try:
            export_state_snapshot(state)
        except Exception:  # pragma: no cover - filesystem issues are logged only
            LOGGER.exception("Failed to persist state snapshot to %s", STATE_SNAPSHOT_FILE)


def _resolve_symbol_argument(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    allow_state_fallback: bool = False,
) -> tuple[str | None, bool]:
    """Return the symbol argument and whether it originated from user input."""

    if getattr(context, "args", None):
        candidate = str(context.args[0]).strip()
        if candidate:
            return _normalise_symbol(candidate), True

    if not allow_state_fallback:
        return None, False

    state = _state_from_context(context)
    if state.last_symbol:
        return _normalise_symbol(state.last_symbol), False
    return None, False


def _infer_symbol_from_positions(payload: Any) -> str | None:
    """Best-effort extraction of a symbol from a positions payload."""

    if isinstance(payload, Mapping):
        candidate = payload.get("symbol") or payload.get("pair") or payload.get("market")
        if candidate:
            return _normalise_symbol(str(candidate))

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for entry in payload:
            if isinstance(entry, Mapping):
                candidate = entry.get("symbol") or entry.get("pair") or entry.get("market")
                if candidate:
                    return _normalise_symbol(str(candidate))

    return None


def _is_symbol_required_error(error: BingXClientError) -> bool:
    """Return ``True`` if BingX complained about a missing symbol parameter."""

    message = str(error).lower()
    return "symbol" in message and ("required" in message or "empty" in message)


def _schedule_daily_report(application: Application, settings: Settings, state: BotState) -> None:
    """Schedule or cancel the daily report job based on *state*."""

    job_queue = application.job_queue
    if job_queue is None:
        return

    for job in job_queue.get_jobs_by_name("daily-report"):
        job.schedule_removal()

    if not state.daily_report_time or not settings.telegram_chat_id:
        return

    report_time = _parse_time(state.daily_report_time)
    if report_time is None:
        LOGGER.warning("Invalid daily report time configured: %s", state.daily_report_time)
        return

    job_queue.run_daily(
        _send_daily_report,
        time=report_time,
        name="daily-report",
    )


async def _register_bot_commands(application: Application) -> None:
    """Register the default Telegram command list for the bot."""

    commands = [
        BotCommand("start", "Begrüßung & Schnellzugriff"),
        BotCommand("stop", "Autotrade deaktivieren"),
        BotCommand("status", "Aktuellen Status anzeigen"),
        BotCommand("open", "Position öffnen"),
        BotCommand("close", "Position schließen"),
        BotCommand("report", "BingX Kontoübersicht"),
        BotCommand("positions", "Offene Positionen anzeigen"),
        BotCommand("margin", "Margin anzeigen oder setzen"),
        BotCommand("leverage", "Leverage anzeigen oder setzen"),
        BotCommand("autotrade", "Autotrade an/aus"),
        BotCommand("autotrade_direction", "Autotrade Richtung"),
        BotCommand("set_max_trade", "Max. Tradegröße setzen"),
        BotCommand("daily_report", "Daily Report Zeit"),
        BotCommand("set", "Globale Defaults setzen"),
        BotCommand("halt", "DRY_RUN aktivieren"),
        BotCommand("resume", "DRY_RUN deaktivieren"),
        BotCommand("sync", "Einstellungen neu laden"),
    ]

    with contextlib.suppress(Exception):
        await application.bot.set_my_commands(commands)


async def _send_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback executed by the job queue to emit the daily report."""

    settings = _get_settings(context)
    if not settings or not settings.telegram_chat_id:
        return

    if not _bingx_credentials_available(settings):
        LOGGER.info("Skipping daily report because BingX credentials are missing")
        return

    state = _state_from_context(context)

    try:
        balance, positions, margin_data = await _fetch_bingx_snapshot(settings, state)
    except BingXClientError as exc:
        LOGGER.error("Daily report failed: %s", exc)
        with contextlib.suppress(Exception):
            await context.bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=f"❌ Daily report failed: {exc}",
            )
        return

    message = "🗓 Daily Report\n" + _build_report_message(balance, positions, margin_data)
    await context.bot.send_message(chat_id=settings.telegram_chat_id, text=message)


def _get_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings | None:
    """Return the shared ``Settings`` instance stored in the application."""

    settings = context.application.bot_data.get("settings") if context.application else None
    if isinstance(settings, Settings):
        return settings
    return None


def _is_dry_run_enabled(settings: Settings | None, application: Application | None) -> bool:
    override = None
    if application is not None:
        override = application.bot_data.get("dry_run_override")
    if override is not None:
        return bool(override)
    return bool(settings.dry_run if settings else False)


def _bingx_credentials_available(settings: Settings | None) -> bool:
    """Return ``True`` when BingX credentials are configured."""

    return bool(settings and settings.bingx_api_key and settings.bingx_api_secret)


def _store_manual_alert(application: Application, alert: Mapping[str, Any]) -> str:
    """Persist *alert* for manual trade callbacks and return its identifier."""

    alerts = application.bot_data.get("manual_alerts")
    if not isinstance(alerts, dict):
        alerts = {}
        application.bot_data["manual_alerts"] = alerts

    order = application.bot_data.get("manual_alert_order")
    if not isinstance(order, deque):
        order = deque()
        application.bot_data["manual_alert_order"] = order

    while len(order) >= MANUAL_ALERT_HISTORY_LIMIT:
        oldest = order.popleft()
        alerts.pop(oldest, None)

    alert_id = uuid.uuid4().hex
    try:
        alerts[alert_id] = dict(alert)
    except Exception:
        alerts[alert_id] = alert
    order.append(alert_id)
    return alert_id


def _get_manual_alert(application: Application, alert_id: str) -> Mapping[str, Any] | None:
    """Return a previously stored alert for manual trading."""

    alerts = application.bot_data.get("manual_alerts")
    if isinstance(alerts, dict):
        alert = alerts.get(alert_id)
        if isinstance(alert, Mapping):
            return alert
    return None


def _format_number(value: Any) -> str:
    """Format a numeric value with a small helper to avoid noisy decimals."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    return f"{number:,.4f}".rstrip("0").rstrip(".")


def _humanize_key(key: str) -> str:
    """Convert API keys to a human readable label."""

    label = re.sub(r"(?<!^)(?=[A-Z])", " ", key.replace("_", " ")).strip()
    titled = label.title()
    return titled.replace("Pnl", "PnL").replace("Usdt", "USDT")


def _is_usdc_currency(entry: Mapping[str, Any]) -> bool:
    """Return ``True`` when the mapping represents a USDC balance."""

    currency = entry.get("currency") or entry.get("asset") or entry.get("symbol")
    return isinstance(currency, str) and currency.upper() == "USDC"


def _format_balance_payload(balance: Any) -> list[str]:
    """Return a formatted list of lines describing the account balance."""

    def _format_balance_entry(entry: Mapping[str, Any]) -> str | list[str]:
        if _is_usdc_currency(entry):
            return ""
        equity = (
            entry.get("equity")
            or entry.get("totalEquity")
            or entry.get("balance")
        )
        available = entry.get("availableMargin") or entry.get("availableBalance")
        pnl = entry.get("unrealizedPnL") or entry.get("unrealizedProfit")
        currency = entry.get("currency") or entry.get("asset") or entry.get("symbol")

        parts: list[str] = []
        if equity is not None:
            parts.append(f"Equity {_format_number(equity)}")
        elif entry.get("balance") is not None:
            parts.append(f"Balance {_format_number(entry['balance'])}")
        if available is not None:
            parts.append(f"Verfügbar {_format_number(available)}")
        if pnl is not None:
            parts.append(f"Unrealized PnL {_format_number(pnl)}")

        if parts:
            prefix = f"• {currency}: " if currency else "• "
            return prefix + ", ".join(parts)

        # Fallback to printing every key/value pair when nothing recognisable was found
        return [
            f"• {_humanize_key(str(key))}: {_format_number(value)}"
            for key, value in entry.items()
        ]

    if balance is None:
        return []

    lines: list[str] = ["💼 Kontostand"]

    if isinstance(balance, Mapping):
        if _is_usdc_currency(balance):
            return []
        formatted = _format_balance_entry(balance)
        if isinstance(formatted, list):
            lines.extend(formatted)
        elif formatted:
            lines.append(formatted)
        return lines

    if isinstance(balance, Sequence) and not isinstance(balance, (str, bytes, bytearray)):
        added = False
        for entry in balance:
            if isinstance(entry, Mapping):
                if _is_usdc_currency(entry):
                    continue
                formatted = _format_balance_entry(entry)
                if isinstance(formatted, list):
                    lines.extend(formatted)
                elif formatted:
                    lines.append(formatted)
                added = True
            else:
                lines.append(f"• {entry}")
                added = True
        return lines if added else []

    return ["💼 Kontostand", f"• {balance}"]


def _format_margin_payload(payload: Any) -> str:
    """Return a human readable string for margin data."""

    if isinstance(payload, Mapping):
        if _is_usdc_currency(payload):
            return ""
        known_keys = (
            "availableMargin",
            "availableBalance",
            "margin",
            "usedMargin",
            "unrealizedPnL",
            "unrealizedProfit",
            "marginRatio",
        )
        lines = ["💰 Margin-Überblick:"]
        added = False
        for key in known_keys:
            if key in payload and payload[key] is not None:
                lines.append(f"• {_humanize_key(key)}: {_format_number(payload[key])}")
                added = True
        if not added:
            for key, value in payload.items():
                lines.append(f"• {_humanize_key(str(key))}: {_format_number(value)}")
        return "\n".join(lines)

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        lines = ["💰 Margin-Überblick:"]
        for entry in payload:
            if isinstance(entry, Mapping):
                symbol = entry.get("symbol") or entry.get("currency") or entry.get("asset") or "Unknown"
                if isinstance(symbol, str) and symbol.upper() == "USDC":
                    continue
                available = entry.get("availableMargin") or entry.get("availableBalance")
                used = entry.get("usedMargin") or entry.get("margin")
                ratio = entry.get("marginRatio")
                parts = [symbol]
                if available is not None:
                    parts.append(f"available {_format_number(available)}")
                if used is not None:
                    parts.append(f"used {_format_number(used)}")
                if ratio is not None:
                    parts.append(f"ratio {_format_number(ratio)}")
                lines.append("• " + ", ".join(parts))
            else:
                lines.append(f"• {entry}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    return "💰 Margin-Überblick: " + str(payload)


def _format_percentage(value: Any) -> str | None:
    """Format a numeric percentage value while keeping free-form strings intact."""

    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None

    if 0 <= number <= 1:
        number *= 100

    formatted = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def _format_tradingview_alert(alert: Mapping[str, Any], state: BotState | None = None) -> str:
    """Return a readable representation of a TradingView alert."""

    if not isinstance(alert, Mapping):
        return "📢 TradingView Signal\n" + str(alert)

    strategy_data = alert.get("strategy")
    strategy = strategy_data if isinstance(strategy_data, Mapping) else {}

    lines = ["SIGNAL 🔁"]

    message = None
    for key in ("message", "alert", "text", "body", "comment"):
        value = alert.get(key)
        if value:
            message = str(value)
            break
    if not message and strategy:
        for key in ("order_comment", "comment", "strategy"):
            value = strategy.get(key)
            if value:
                message = str(value)
                break

    if message:
        lines.append(message)

    def _coerce_number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    symbol = _extract_symbol_from_alert(alert) or ""

    side_raw = (
        alert.get("side")
        or alert.get("signal")
        or alert.get("action")
        or alert.get("direction")
        or strategy.get("order_action")
        or strategy.get("side")
        or ""
    )
    side_value = str(side_raw).strip().lower()
    if side_value in {"buy", "long"}:
        side_display = "🟢 Kauf"
    elif side_value in {"sell", "short"}:
        side_display = "🔴 Verkauf"
    else:
        side_display = None

    price_value = (
        _coerce_number(alert.get("price"))
        or _coerce_number(alert.get("orderPrice"))
        or _coerce_number(strategy.get("order_price"))
    )

    quantity_value = (
        _coerce_number(alert.get("quantity"))
        or _coerce_number(alert.get("qty"))
        or _coerce_number(alert.get("size"))
        or _coerce_number(alert.get("amount"))
        or _coerce_number(alert.get("orderSize"))
        or _coerce_number(strategy.get("order_contracts"))
    )

    timeframe = None
    for key in ("interval", "timeframe", "resolution"):
        value = alert.get(key)
        if value:
            timeframe = str(value)
            break
    if not timeframe and strategy:
        timeframe_candidate = strategy.get("interval") or strategy.get("timeframe")
        if timeframe_candidate:
            timeframe = str(timeframe_candidate)

    extra_lines: list[str] = []
    asset = (
        alert.get("asset")
        or alert.get("symbol")
        or alert.get("pair")
        or symbol
    )
    payout = _format_percentage(alert.get("payout") or alert.get("profit"))
    accuracy = _format_percentage(alert.get("accuracy") or alert.get("winrate"))
    expiration = (
        alert.get("expiration")
        or alert.get("expiry")
        or alert.get("duration")
        or timeframe
    )

    detail_lines: list[str] = []
    if asset:
        detail_lines.append(f"Asset: {asset}")
    if payout:
        detail_lines.append(f"Payout: {payout}")
    if accuracy:
        detail_lines.append(f"Accuracy: {accuracy}")
    if expiration:
        detail_lines.append(f"Expiration: {expiration}")

    autotrade_enabled: bool | None = None
    if state is not None:
        autotrade_enabled = state.autotrade_enabled
    elif "autotrade" in alert:
        autotrade_enabled = bool(alert.get("autotrade"))

    autotrade_line = None
    if autotrade_enabled is not None:
        autotrade_line = "Auto-trade: On" if autotrade_enabled else "Auto-trade: Off"

    extra_lines: list[str] = []
    if symbol:
        extra_lines.append(f"• Paar: {symbol}")
    if side_display:
        extra_lines.append(f"• Richtung: {side_display}")
    if quantity_value is not None:
        extra_lines.append(f"• Menge: {_format_number(quantity_value)}")
    if price_value is not None:
        extra_lines.append(f"• Preis: {_format_number(price_value)}")
    if timeframe and timeframe != expiration:
        extra_lines.append(f"• Timeframe: {timeframe}")

    use_custom_layout = bool(detail_lines or autotrade_line or message or extra_lines)

    if use_custom_layout:
        if detail_lines:
            lines.append("")
            lines.extend(detail_lines)
        if autotrade_line:
            lines.append("")
            lines.append(autotrade_line)
        if message:
            lines.append("")
            lines.append(message)
        if extra_lines:
            lines.append("")
            lines.extend(extra_lines)
        return "\n".join(lines)

    # Fall back to the generic representation if no details could be extracted.
    lines = ["📢 TradingView Signal"]
    if message:
        lines.append(message)
    if extra_lines:
        if message:
            lines.append("")
        lines.extend(extra_lines)
    if len(lines) == 1:
        formatted = json.dumps(alert, indent=2, sort_keys=True, default=str)
        lines.append(formatted)
    return "\n".join(lines)


def _format_positions_payload(payload: Any) -> str:
    """Return a human readable string for open positions."""

    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        lines = []
        for entry in payload:
            if isinstance(entry, Mapping):
                symbol = entry.get("symbol") or entry.get("pair") or "Unknown"
                side = entry.get("side") or entry.get("positionSide") or entry.get("direction")
                size = entry.get("positionSize") or entry.get("size") or entry.get("quantity")
                leverage = entry.get("leverage")
                pnl = entry.get("unrealizedPnL") or entry.get("unrealizedProfit")

                parts = [symbol]
                if side:
                    parts.append(str(side))
                if size is not None:
                    parts.append(f"size {_format_number(size)}")
                if leverage is not None:
                    parts.append(f"{_format_number(leverage)}x")
                if pnl is not None:
                    parts.append(f"PnL {_format_number(pnl)}")

                lines.append("• " + ", ".join(parts))
            else:
                lines.append(f"• {entry}")
        if not lines:
            return "📈 Keine offenen Futures-Positionen gefunden."
        return "📈 Offene Futures-Positionen:\n" + "\n".join(lines)

    if isinstance(payload, Mapping):
        return "📈 Offene Futures-Positionen:\n" + "\n".join(
            f"• {_humanize_key(str(key))}: {_format_number(value)}" for key, value in payload.items()
        )

    return "📈 Offene Futures-Positionen: " + str(payload)


async def _fetch_bingx_snapshot(
    settings: Settings, state: BotState | None = None
) -> tuple[Any, Any, Any]:
    """Return balance, positions and margin information from BingX."""

    preferred_symbol = _normalise_symbol(state.last_symbol) if state and state.last_symbol else None

    async with BingXClient(
        api_key=settings.bingx_api_key or "",
        api_secret=settings.bingx_api_secret or "",
        base_url=settings.bingx_base_url,
        recv_window=settings.bingx_recv_window,
    ) as client:
        balance = await client.get_account_balance()
        positions = await client.get_open_positions()

        margin: Any | None = None
        try:
            margin = await client.get_margin_summary(symbol=preferred_symbol)
        except BingXClientError as exc:
            if preferred_symbol is None and _is_symbol_required_error(exc):
                inferred_symbol = _infer_symbol_from_positions(positions)
                if inferred_symbol:
                    try:
                        margin = await client.get_margin_summary(symbol=inferred_symbol)
                    except BingXClientError as retry_exc:
                        LOGGER.warning("Retrying margin lookup for %s failed: %s", inferred_symbol, retry_exc)
                else:
                    LOGGER.warning("Margin endpoint requires a symbol but none could be inferred from positions.")
            elif "100400" in str(exc).lower() and "api" in str(exc).lower():
                LOGGER.warning("Margin endpoint not available on this BingX account: %s", exc)
            else:
                raise

    return balance, positions, margin


def _build_report_message(balance: Any, positions: Any, margin: Any) -> str:
    """Return a formatted multi-section report string."""

    lines: list[str] = ["📊 BingX Futures Report"]

    balance_lines = _format_balance_payload(balance)
    if balance_lines:
        lines.append("")
        lines.extend(balance_lines)

    positions_block = _format_positions_payload(positions)
    if positions_block:
        lines.append("")
        lines.append(positions_block)

    if margin is not None:
        margin_block = _format_margin_payload(margin)
        if margin_block:
            lines.append("")
            lines.append(margin_block)

    return "\n".join(line for line in lines if line)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a simple status message."""

    if not update.message:
        return

    state = _state_from_context(context)
    settings = _get_settings(context)
    dry_run_active = _is_dry_run_enabled(settings, context.application)
    autotrade_enabled = bool(state.autotrade_enabled)

    global_cfg = state.global_trade
    margin_coin = state.normalised_margin_asset()
    margin_value = _format_number(global_cfg.margin_usdt)
    if margin_coin:
        margin_display = f"{margin_value} {margin_coin}"
    else:
        margin_display = margin_value

    if global_cfg.lev_long == global_cfg.lev_short:
        leverage_display = f"{global_cfg.lev_long}x"
    else:
        leverage_display = f"Long {global_cfg.lev_long}x / Short {global_cfg.lev_short}x"

    lines = [
        "📟 Statusübersicht",
        f"AUTOTRADE: {'1' if autotrade_enabled else '0'}",
        f"DRY_RUN: {'1' if dry_run_active else '0'}",
        f"MODE: {'hedge' if global_cfg.hedge_mode else 'oneway'}",
        f"MGNMODE: {'isolated' if global_cfg.isolated else 'cross'}",
        f"MARGIN: {margin_display}",
        f"LEV: {leverage_display}",
        f"TIF: {global_cfg.normalised_time_in_force()}",
    ]

    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide helpful information to the user."""

    if not update.message:
        return

    await update.message.reply_text(
        "Verfügbare Befehle:\n"
        "/start - Begrüßung und Schnellzugriff.\n"
        "/stop - Autotrade deaktivieren.\n"
        "/status - Aktuellen Bot-Status anzeigen.\n"
        "/report - Kontoübersicht von BingX.\n"
        "/positions - Offene Positionen anzeigen.\n"
        "/margin <USDT> - Globale Margin setzen.\n"
        "/lev <x> - Globales Leverage setzen.\n"
        "/mode hedge|oneway - Positionsmodus wählen.\n"
        "/mgnmode isolated|cross - Margin-Modus setzen.\n"
        "/tif GTC|IOC|FOK - Default Time-in-Force wählen.\n"
        "/long|/short <Symbol> [Optionen] - Position im Hedge-Mode eröffnen.\n"
        "/open <Symbol> [Optionen] - Position im One-Way-Mode eröffnen.\n"
        "/close … - Positionen schließen (reduce-only).\n"
        "/autotrade on|off - Autotrade schalten.\n"
        "/autotrade_direction long|short|both - Erlaubte Signalrichtung setzen.\n"
        "/set_max_trade <Wert> - Maximale Positionsgröße festlegen.\n"
        "/daily_report <HH:MM|off> - Uhrzeit des Daily Reports setzen.\n"
        "/sync - Einstellungen neu laden."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message and show the quick access keyboard."""

    if not update.message:
        return

    state = _state_from_context(context)
    welcome_lines = [
        "🚀 Willkommen bei TVTelegramBingX!",
        "Dieser Bot verbindet TradingView Signale mit BingX.",
        "Nutze das Schnellmenü oder /help für Details.",
        f"Autotrade ist derzeit {'aktiviert' if state.autotrade_enabled else 'deaktiviert'}.",
    ]

    await update.message.reply_text("\n".join(welcome_lines), reply_markup=MAIN_KEYBOARD)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable autotrading via shortcut command."""

    if not update.message:
        return

    state = _state_from_context(context)
    if state.autotrade_enabled:
        state.autotrade_enabled = False
        _persist_state(context)
        message = "⏹ Autotrade wurde deaktiviert."
    else:
        message = "Autotrade war bereits deaktiviert."

    await update.message.reply_text(message, reply_markup=MAIN_KEYBOARD)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return an overview of the current BingX account status."""

    if not update.message:
        return

    settings = _get_settings(context)
    if not _bingx_credentials_available(settings):
        await update.message.reply_text(
            "⚠️ BingX API credentials are not configured. Set BINGX_API_KEY and BINGX_API_SECRET to enable reports."
        )
        return

    assert settings  # mypy reassurance

    state = _state_from_context(context)

    try:
        balance, positions, margin_data = await _fetch_bingx_snapshot(settings, state)
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to contact BingX: {exc}")
        return

    await update.message.reply_text(_build_report_message(balance, positions, margin_data))


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return currently open positions from BingX."""

    if not update.message:
        return

    settings = _get_settings(context)
    if not _bingx_credentials_available(settings):
        await update.message.reply_text(
            "⚠️ BingX API credentials are not configured. Set BINGX_API_KEY and BINGX_API_SECRET to enable this command."
        )
        return

    assert settings

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
            recv_window=settings.bingx_recv_window,
        ) as client:
            data = await client.get_open_positions()
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch positions: {exc}")
        return

    await update.message.reply_text(_format_positions_payload(data))


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update or display the global margin budget used for sizing."""

    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            f"Globale Margin: {state.global_trade.margin_usdt:.2f} USDT"
        )
        return

    if len(args) != 1:
        await update.message.reply_text(
            "Bitte genau einen Margin-Wert angeben, z. B. /margin 150."
        )
        return

    margin_value = _parse_float_token(args[0])
    if margin_value is None:
        await update.message.reply_text("Der Margin-Wert muss numerisch sein.")
        return
    if margin_value <= 0:
        await update.message.reply_text("Der Margin-Wert muss positiv sein.")
        return

    state.set_margin(margin_value)
    _persist_state(context)

    await update.message.reply_text(
        f"OK. Globale Margin = {margin_value:.2f} USDT\n\n{_format_global_trade_summary(state)}"
    )


async def leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set or display the global leverage defaults via /lev."""

    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if not args:
        cfg = state.global_trade
        if cfg.lev_long == cfg.lev_short:
            message = f"Globales Leverage: {cfg.lev_long}x"
        else:
            message = (
                f"Globales Leverage: Long {cfg.lev_long}x / Short {cfg.lev_short}x"
            )
        await update.message.reply_text(message)
        return

    if len(args) != 1:
        await update.message.reply_text("Bitte genau einen Leverage-Wert angeben, z. B. /lev 10.")
        return

    leverage_value = _parse_int_token(args[0])
    if leverage_value is None:
        await update.message.reply_text("Leverage muss numerisch sein.")
        return
    if leverage_value <= 0:
        await update.message.reply_text("Leverage muss größer als 0 sein.")
        return

    state.set_leverage(lev_long=leverage_value)
    state.leverage = float(leverage_value)
    _persist_state(context)
    invalidate_symbol_configuration()

    await update.message.reply_text(
        f"OK. Globales Leverage = {leverage_value}x\n\n{_format_global_trade_summary(state)}"
    )


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch between hedge and one-way position modes."""

    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if not args:
        current = "hedge" if state.global_trade.hedge_mode else "oneway"
        await update.message.reply_text(f"Aktueller Positionsmodus: {current}")
        return

    if len(args) != 1:
        await update.message.reply_text("Verwende /mode hedge oder /mode oneway.")
        return

    token = args[0].strip().lower()
    if token not in {"hedge", "oneway"}:
        await update.message.reply_text("Ungültiger Modus. Erlaubt: hedge oder oneway.")
        return

    state.global_trade.hedge_mode = token == "hedge"
    _persist_state(context)
    invalidate_symbol_configuration()

    await update.message.reply_text(f"OK. Positionsmodus = {token}.")


async def mgnmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure the global margin mode for new symbols."""

    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if not args:
        current = "isolated" if state.global_trade.isolated else "cross"
        await update.message.reply_text(f"Aktueller Margin-Modus: {current}")
        return

    if len(args) != 1:
        await update.message.reply_text("Verwende /mgnmode isolated oder /mgnmode cross.")
        return

    token = _normalise_margin_mode_token(args[0])
    if token not in {"isolated", "cross"}:
        await update.message.reply_text("Ungültiger Margin-Modus. Erlaubt: isolated oder cross.")
        return

    state.global_trade.isolated = token == "isolated"
    state.margin_mode = token
    _persist_state(context)
    invalidate_symbol_configuration()

    await update.message.reply_text(f"OK. Margin-Modus = {token}.")


async def tif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the default time-in-force for limit orders."""

    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            f"Aktuelles Time-in-Force: {state.global_trade.normalised_time_in_force()}"
        )
        return

    if len(args) != 1:
        await update.message.reply_text("Verwende /tif GTC|IOC|FOK.")
        return

    token = args[0].strip().upper()
    if token not in {"GTC", "IOC", "FOK"}:
        await update.message.reply_text("Ungültiges TIF. Erlaubt: GTC, IOC, FOK.")
        return

    state.global_trade.set_time_in_force(token)
    _persist_state(context)

    await update.message.reply_text(
        f"OK. Globales TIF = {state.global_trade.normalised_time_in_force()}"
    )


async def autotrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle autotrading on or off."""

    if not update.message:
        return

    state = _state_from_context(context)
    if not context.args:
        status = "aktiviert" if state.autotrade_enabled else "deaktiviert"
        await update.message.reply_text(f"Autotrade ist aktuell {status}.")
        return

    command = context.args[0].strip().lower()
    if command in {"on", "an", "start"}:
        if state.autotrade_enabled:
            message = "Autotrade war bereits aktiviert."
        else:
            state.autotrade_enabled = True
            _persist_state(context)
            message = "🟢 Autotrade wurde aktiviert."
    elif command in {"off", "aus", "stop"}:
        if state.autotrade_enabled:
            state.autotrade_enabled = False
            _persist_state(context)
            message = "🔴 Autotrade wurde deaktiviert."
        else:
            message = "Autotrade war bereits deaktiviert."
    else:
        message = "Bitte verwende /autotrade on oder /autotrade off."

    await update.message.reply_text(message)


async def _apply_leverage_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed_args: tuple[str | None, bool, float, str | None, str],
) -> None:
    symbol, symbol_was_provided, leverage_value, margin_coin, margin_mode = parsed_args

    state = _state_from_context(context)
    state.leverage = leverage_value
    if margin_mode:
        state.margin_mode = margin_mode
    if margin_coin:
        state.margin_asset = margin_coin
    if symbol and symbol_was_provided:
        state.last_symbol = symbol

    _persist_state(context)
    invalidate_symbol_configuration(symbol if symbol_was_provided else None)

    responses = [f"Leverage auf {leverage_value:g}x gesetzt."]
    if margin_mode:
        responses.append(f"Margin-Modus auf {state.normalised_margin_mode()} gesetzt.")
    if margin_coin:
        responses.append(f"Margin-Coin auf {state.normalised_margin_asset()} gesetzt.")

    settings = _get_settings(context)
    symbol_for_api = symbol if symbol_was_provided else None

    if symbol_for_api and _bingx_credentials_available(settings):
        assert settings
        try:
            async with BingXClient(
                api_key=settings.bingx_api_key or "",
                api_secret=settings.bingx_api_secret or "",
                base_url=settings.bingx_base_url,
                recv_window=settings.bingx_recv_window,
            ) as client:
                await client.set_leverage(
                    symbol=symbol_for_api,
                    leverage=leverage_value,
                    margin_mode=state.normalised_margin_mode(),
                    margin_coin=state.normalised_margin_asset(),
                )
        except BingXClientError as exc:
            responses.append(f"⚠️ BingX Leverage konnte nicht gesetzt werden: {exc}")
        else:
            responses.append(f"✅ BingX Leverage für {symbol_for_api} aktualisiert.")
    elif symbol_for_api is None:
        responses.append(
            "ℹ️ Einstellung lokal gespeichert. Verwende /leverage <Symbol> <Wert> [Modus] [Coin], um BingX zu aktualisieren."
        )
    elif not _bingx_credentials_available(settings):
        responses.append("⚠️ BingX API Zugangsdaten fehlen – Einstellungen wurden lokal gespeichert.")

    await update.message.reply_text("\n".join(responses))


async def _apply_margin_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed_args: tuple[str | None, bool, str, str | None],
) -> None:
    symbol, symbol_was_provided, margin_mode, margin_coin = parsed_args

    await _apply_leverage_update(update, context, parsed)


async def _apply_margin_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed_args: tuple[str | None, bool, str, str | None],
) -> None:
    symbol, symbol_was_provided, margin_mode, margin_coin = parsed_args

    state = _state_from_context(context)
    state.margin_mode = margin_mode
    if margin_coin:
        state.margin_asset = margin_coin
    if symbol and symbol_was_provided:
        state.last_symbol = symbol

    _persist_state(context)
    invalidate_symbol_configuration(symbol if symbol_was_provided else None)

    responses = [f"Margin-Modus auf {state.normalised_margin_mode()} gesetzt."]
    if margin_coin:
        responses.append(f"Margin-Coin auf {state.normalised_margin_asset()} gesetzt.")

    settings = _get_settings(context)
    symbol_for_api = symbol if symbol_was_provided else None

    if symbol_for_api and _bingx_credentials_available(settings):
        assert settings  # for type-checkers
        try:
            async with BingXClient(
                api_key=settings.bingx_api_key or "",
                api_secret=settings.bingx_api_secret or "",
                base_url=settings.bingx_base_url,
                recv_window=settings.bingx_recv_window,
            ) as client:
                await client.set_margin_type(
                    symbol=symbol_for_api,
                    margin_mode=state.normalised_margin_mode(),
                    margin_coin=state.normalised_margin_asset(),
                )
        except BingXClientError as exc:
            responses.append(f"⚠️ BingX Margin konnte nicht gesetzt werden: {exc}")
        else:
            responses.append(f"✅ BingX Margin für {symbol_for_api} aktualisiert.")
    elif symbol_for_api is None:
        responses.append(
            "ℹ️ Einstellung lokal gespeichert. Verwende /margin <Symbol> [Coin] <Modus>, um BingX zu aktualisieren."
        )
    elif not _bingx_credentials_available(settings):
        responses.append("⚠️ BingX API Zugangsdaten fehlen – Einstellungen wurden lokal gespeichert.")

    await update.message.reply_text("\n".join(responses))


async def set_margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure the margin mode used for autotrade orders."""

    if not update.message:
        return

    state = _state_from_context(context)

    try:
        parsed = _parse_margin_command_args(
            context.args or [],
            default_mode=state.margin_mode,
            default_coin=state.margin_asset,
        )
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    await _apply_margin_update(update, context, parsed)


async def set_max_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure the maximum order size used during autotrade."""

    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Bitte gib eine Positionsgröße an. Beispiel: /set_max_trade 50 (für 50 Kontrakte)"
        )
        return

    value_raw = context.args[0]
    if value_raw.lower() in {"off", "none", "0"}:
        state = _state_from_context(context)
        state.max_trade_size = None
        _persist_state(context)
        await update.message.reply_text("Maximale Trade-Größe entfernt.")
        return

    try:
        value = float(value_raw)
    except ValueError:
        await update.message.reply_text("Ungültige Zahl. Beispiel: /set_max_trade 25")
        return

    if value <= 0:
        await update.message.reply_text("Der Wert muss größer als 0 sein.")
        return

    state = _state_from_context(context)
    state.max_trade_size = value
    _persist_state(context)
    await update.message.reply_text(f"Maximale Trade-Größe auf {_format_number(value)} gesetzt.")


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for ``/set global …`` shortcuts."""

    if not update.message:
        return

    args = context.args or []
    if len(args) < 2 or args[0].strip().lower() != "global":
        await update.message.reply_text(
            "Nutzung: /set global <margin|lev|tif|mode|mgnmode> <Wert>"
        )
        return

    subcommand = args[1].strip().lower()
    values = args[2:]
    state = _state_from_context(context)

    invalidate_required = False
    response_detail: str | None = None

    if subcommand == "margin":
        if not values:
            await update.message.reply_text("Bitte gib einen Margin-Wert in USDT an.")
            return
        margin_value = _coerce_float_value(values[0])
        if margin_value is None:
            await update.message.reply_text("Margin-Wert muss numerisch sein.")
            return
        if margin_value < 0:
            await update.message.reply_text("Margin-Wert muss größer oder gleich 0 sein.")
            return
        state.set_margin(margin_value)
        response_detail = f"Margin = {_format_number(margin_value)} USDT"
        invalidate_required = True
    elif subcommand == "lev":
        if not values:
            await update.message.reply_text("Bitte gib einen Leverage-Wert an.")
            return
        leverage_value = _parse_int_token(values[0])
        if leverage_value is None or leverage_value <= 0:
            await update.message.reply_text("Leverage muss größer als 0 sein.")
            return
        state.set_leverage(lev_long=leverage_value, lev_short=leverage_value)
        response_detail = f"Leverage = {leverage_value}x"
        invalidate_required = True
    elif subcommand == "tif":
        if not values:
            await update.message.reply_text("Bitte gib ein Time-in-Force an (GTC|IOC|FOK).")
            return
        tif_token = values[0].strip().upper()
        if tif_token not in {"GTC", "IOC", "FOK"}:
            await update.message.reply_text("Ungültiges TIF. Erlaubt: GTC, IOC, FOK.")
            return
        state.global_trade.set_time_in_force(tif_token)
        response_detail = f"TIF = {tif_token}"
    elif subcommand == "mode":
        if not values:
            await update.message.reply_text("Bitte gib hedge oder oneway an.")
            return
        mode_token = values[0].strip().lower()
        if mode_token not in {"hedge", "oneway"}:
            await update.message.reply_text("Ungültiger Modus. Erlaubt: hedge, oneway.")
            return
        state.global_trade.hedge_mode = mode_token == "hedge"
        response_detail = f"Position Mode = {mode_token}"
        invalidate_required = True
    elif subcommand in {"mgnmode", "marginmode", "mgn"}:
        if not values:
            await update.message.reply_text("Bitte gib isolated oder cross an.")
            return
        mode_token = values[0].strip().lower()
        if mode_token not in {"isolated", "cross", "crossed"}:
            await update.message.reply_text("Ungültiger Margin-Modus. Erlaubt: isolated, cross.")
            return
        state.global_trade.isolated = mode_token != "cross"
        state.margin_mode = "isolated" if state.global_trade.isolated else "cross"
        response_detail = f"Margin-Modus = {'isolated' if state.global_trade.isolated else 'cross'}"
        invalidate_required = True
    else:
        await update.message.reply_text(
            "Unbekannte Option. Verwende margin, lev, tif, mode oder mgnmode."
        )
        return

    _persist_state(context)
    if invalidate_required:
        invalidate_symbol_configuration()

    summary = _format_global_trade_summary(state)
    if response_detail is None:
        response_detail = "Einstellungen aktualisiert."

    await update.message.reply_text(f"Globals aktualisiert: {response_detail}\n\n{summary}")


async def set_autotrade_direction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure which signal directions are executed automatically."""

    if not update.message:
        return

    state = _state_from_context(context)

    if not context.args:
        direction_map = {
            "long": "Nur Long",
            "short": "Nur Short",
            "both": "Long & Short",
        }
        current = direction_map.get(state.normalised_autotrade_direction(), "Long & Short")
        await update.message.reply_text(
            "Aktuelle Einstellung: "
            f"{current}. Nutze /autotrade_direction long|short|both für Änderungen."
        )
        return

    token = context.args[0].strip().lower()
    if token in {"long", "long_only", "only_long", "longonly"}:
        new_value = "long"
        label = "Nur Long"
    elif token in {"short", "short_only", "only_short", "shortonly"}:
        new_value = "short"
        label = "Nur Short"
    elif token in {"both", "all", "beide", "both_sides"}:
        new_value = "both"
        label = "Long & Short"
    else:
        await update.message.reply_text(
            "Ungültige Option. Verwende /autotrade_direction long|short|both."
        )
        return

    state.autotrade_direction = new_value
    _persist_state(context)
    await update.message.reply_text(f"Autotrade-Signaleinstellung auf {label} gesetzt.")


async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure the time for the automated daily report."""

    if not update.message:
        return

    state = _state_from_context(context)

    if not context.args:
        current = state.daily_report_time or "ausgeschaltet"
        await update.message.reply_text(f"Aktuelle Einstellung: {current}")
        return

    argument = context.args[0].strip().lower()
    if argument in {"off", "aus", "none"}:
        state.daily_report_time = None
        _persist_state(context)
        _reschedule_daily_report(context)
        await update.message.reply_text("Daily Report deaktiviert.")
        return

    parsed = _parse_time(argument)
    if parsed is None:
        await update.message.reply_text("Ungültige Uhrzeit. Bitte HH:MM im 24h-Format verwenden.")
        return

    state.daily_report_time = argument
    _persist_state(context)
    _reschedule_daily_report(context)
    await update.message.reply_text(f"Daily Report Uhrzeit auf {argument} gesetzt.")


async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload the persisted state from disk."""

    if not update.message or not context.application:
        return

    state_file = Path(context.application.bot_data.get("state_file", STATE_FILE))
    state = load_state(state_file)
    context.application.bot_data["state"] = state
    try:
        export_state_snapshot(state)
    except Exception:  # pragma: no cover - filesystem issues are logged only
        LOGGER.exception("Failed to persist state snapshot to %s", STATE_SNAPSHOT_FILE)
    _reschedule_daily_report(context)
    await update.message.reply_text("Einstellungen wurden neu geladen.")


def _bool_from_value(value: Any) -> bool | None:
    """Best-effort conversion of different payload values into booleans."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _infer_intent(side: str | None, position_side: str | None, reduce_only: bool) -> str:
    """Derive the trading intent token from order parameters."""

    side_token = (side or "").strip().upper()
    position_token = (position_side or "").strip().upper()

    if reduce_only:
        if position_token == "LONG":
            return "LONG_CLOSE"
        if position_token == "SHORT":
            return "SHORT_CLOSE"
        if side_token == "SELL":
            return "LONG_CLOSE"
        if side_token == "BUY":
            return "SHORT_CLOSE"
        return "LONG_CLOSE"

    if position_token == "LONG":
        return "LONG_OPEN"
    if position_token == "SHORT":
        return "SHORT_OPEN"
    if side_token == "BUY":
        return "LONG_OPEN"
    if side_token == "SELL":
        return "SHORT_OPEN"
    return "LONG_OPEN"


def _prepare_autotrade_order(
    alert: Mapping[str, Any],
    state: BotState,
    snapshot: Mapping[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    side_override: str | None = None,
    enforce_direction_rules: bool = True,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the BingX order payload for an alert or a failure reason."""

    if not isinstance(alert, Mapping):
        return None, "⚠️ Autotrade übersprungen: Ungültiges Signalformat."

    alert = dict(alert)
    whitelist = tuple(settings.symbol_whitelist) if settings and settings.symbol_whitelist else ()
    desired_mode = "hedge" if state.global_trade.hedge_mode else "oneway"
    if settings and settings.position_mode in {"hedge", "oneway"}:
        desired_mode = settings.position_mode

    mapping_reduce_only: bool | None = None
    mapping_position_side: str | None = None
    mapping_has_position = False
    global_cfg = state.global_trade
    global_margin_budget = float(global_cfg.margin_usdt)

    action_token = alert.get("action")
    if isinstance(action_token, str) and action_token.strip():
        try:
            mapping = map_action(action_token, position_mode=desired_mode)
        except ValueError as exc:
            return None, f"⚠️ Autotrade übersprungen: {exc}"
        alert.setdefault("side", mapping.side)
        alert.setdefault("positionSide", mapping.position_side)
        alert.setdefault("reduceOnly", mapping.reduce_only)
        if "order_type" in alert and "type" not in alert:
            alert["type"] = alert.get("order_type")
        mapping_reduce_only = mapping.reduce_only
        mapping_position_side = mapping.position_side
        mapping_has_position = True

    symbol_raw = _extract_symbol_from_alert(alert) or ""
    if not symbol_raw:
        return None, "⚠️ Autotrade übersprungen: Kein Symbol im Signal gefunden."

    try:
        symbol = normalize_symbol(symbol_raw, whitelist=whitelist)
    except SymbolValidationError as exc:
        return None, f"⚠️ Autotrade übersprungen: {exc}"

    side: str | None = None
    if isinstance(side_override, str):
        override_token = side_override.strip().upper()
        if override_token in {"BUY", "SELL"}:
            side = override_token

    if side is None:
        side_raw = (
            alert.get("side")
            or alert.get("signal")
            or alert.get("action")
            or alert.get("direction")
            or ""
        )
        side_value = str(side_raw).strip().lower()
        if side_value in {"buy", "long"}:
            side = "BUY"
        elif side_value in {"sell", "short"}:
            side = "SELL"
        else:
            return None, "⚠️ Autotrade übersprungen: Kein Kauf/Verkauf-Signal erkannt."

    if enforce_direction_rules:
        direction_preference = state.normalised_autotrade_direction()
        if direction_preference == "long" and side != "BUY":
            return None, "⚠️ Autotrade übersprungen: Nur Long-Signale erlaubt."
        if direction_preference == "short" and side != "SELL":
            return None, "⚠️ Autotrade übersprungen: Nur Short-Signale erlaubt."

    quantity_raw = (
        alert.get("quantity")
        or alert.get("qty")
        or alert.get("size")
        or alert.get("positionSize")
        or alert.get("amount")
        or alert.get("orderSize")
    )

    order_type = str(alert.get("orderType") or alert.get("type") or "MARKET").upper()
    if order_type not in {"MARKET", "LIMIT"}:
        order_type = "MARKET"

    time_in_force_raw = (
        alert.get("timeInForce")
        or alert.get("time_in_force")
        or alert.get("tif")
    )
    time_in_force: str | None
    if isinstance(time_in_force_raw, str) and time_in_force_raw.strip():
        tif_token = time_in_force_raw.strip().upper()
        time_in_force = tif_token if tif_token in {"GTC", "IOC", "FOK"} else None
    else:
        time_in_force = None
    default_tif = settings.default_time_in_force if settings else "GTC"
    if order_type == "LIMIT" and time_in_force is None:
        time_in_force = default_tif

    margin_candidates = [
        alert.get("margin"),
        alert.get("margin_usdt"),
        alert.get("marginUsdt"),
        alert.get("marginAmount"),
        alert.get("marginValue"),
    ]
    margin_value: float | None = None
    for candidate in margin_candidates:
        margin_value = _coerce_float_value(candidate)
        if margin_value is not None:
            break

    if margin_value is None:
        margin_coin_candidate = alert.get("margin_coin") or alert.get("marginCoin")
        if isinstance(margin_coin_candidate, str):
            token = margin_coin_candidate.strip()
            if token and not any(char.isalpha() for char in token):
                margin_value = _coerce_float_value(token)
        else:
            margin_value = _coerce_float_value(margin_coin_candidate)

    quantity_value: float | None

    if quantity_raw is None:
        if margin_value is not None:
            if margin_value <= 0:
                return None, "⚠️ Autotrade übersprungen: Margin-Wert muss größer als 0 sein."
            quantity_value = None
        elif global_margin_budget > 0:
            quantity_value = None
        elif state.max_trade_size is not None and state.max_trade_size > 0:
            quantity_value = state.max_trade_size
        else:
            return None, (
                "⚠️ Autotrade übersprungen: Global Margin ist nicht konfiguriert "
                "und keine Positionsgröße angegeben."
            )
    else:
        try:
            quantity_value = float(quantity_raw)
        except (TypeError, ValueError):
            return None, "⚠️ Autotrade übersprungen: Positionsgröße konnte nicht interpretiert werden."

    if quantity_value is not None and quantity_value <= 0:
        return None, "⚠️ Autotrade übersprungen: Positionsgröße muss größer als 0 sein."

    if (
        quantity_value is not None
        and state.max_trade_size is not None
        and quantity_value > state.max_trade_size
    ):
        quantity_value = state.max_trade_size

    if settings and quantity_value is not None:
        min_limits = settings.symbol_min_qty or {}
        max_limits = settings.symbol_max_qty or {}
        min_limit = min_limits.get(symbol)
        if min_limit is not None and quantity_value < min_limit:
            return None, (
                "⚠️ Autotrade übersprungen: Positionsgröße unter Mindestmenge "
                f"{min_limit:g}."
            )
        max_limit = max_limits.get(symbol)
        if max_limit is not None and quantity_value > max_limit:
            quantity_value = max_limit

    leverage_override: int | None = None
    for candidate in (
        alert.get("lev"),
        alert.get("lev_value"),
        alert.get("levValue"),
    ):
        if candidate is None:
            continue
        if isinstance(candidate, (int, float)):
            parsed = int(float(candidate))
        else:
            parsed = _parse_int_token(str(candidate))
        if parsed is not None and parsed > 0:
            leverage_override = parsed
            break

    price_raw = alert.get("orderPrice") or alert.get("price")
    price_value: float | None
    if price_raw is None:
        price_value = None
    else:
        try:
            price_value = float(price_raw)
        except (TypeError, ValueError):
            price_value = None

    if order_type == "LIMIT" and price_value is None:
        return None, "⚠️ Autotrade übersprungen: Limit-Orders benötigen einen Preis."

    reduce_only = _bool_from_value(
        alert.get("reduceOnly")
        or alert.get("reduce_only")
        or alert.get("closePosition")
    )
    if reduce_only is None and mapping_reduce_only is not None:
        reduce_only = mapping_reduce_only
    if reduce_only is None:
        reduce_only = False

    position_side_raw = (
        alert.get("positionSide")
        or alert.get("position_side")
        or alert.get("position")
        or alert.get("posSide")
    )
    position_side: str | None
    if isinstance(position_side_raw, str):
        token = position_side_raw.strip().upper()
        if token in {"LONG", "SHORT"}:
            position_side = token
        else:
            position_side = None
    else:
        position_side = None

    if mapping_position_side is not None:
        if mapping_position_side.strip().upper() == "BOTH":
            position_side = None
        else:
            position_side = mapping_position_side

    client_order_id_raw = (
        alert.get("clientOrderId")
        or alert.get("client_order_id")
        or alert.get("client_id")
    )
    client_order_id = str(client_order_id_raw).strip() if client_order_id_raw else None
    if not client_order_id:
        alert_identifier = (
            alert.get("alert_id")
            or alert.get("alertId")
            or alert.get("id")
        )
        base_payload = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "qty": quantity_value,
            "price": price_value,
            "reduceOnly": reduce_only,
        }
        client_order_id = generate_client_order_id(
            str(alert_identifier) if alert_identifier is not None else None,
            base_payload,
        )

    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity_value,
        "order_type": order_type,
        "margin_mode": state.normalised_margin_mode(),
        "leverage": state.leverage,
        "margin_coin": state.normalised_margin_asset(),
    }


    leverage_for_execution: int | None = None
    if leverage_override is not None:
        leverage_display: float | int = leverage_override
        leverage_for_execution = leverage_override
    else:
        leverage_display = global_cfg.lev_long if side == "BUY" else global_cfg.lev_short
    payload["leverage"] = leverage_display
    if leverage_for_execution is not None:
        payload["leverage_override"] = leverage_for_execution
    if time_in_force is not None:
        payload["time_in_force"] = time_in_force

    effective_margin = (
        margin_value
        if margin_value is not None
        else (global_margin_budget if global_margin_budget > 0 else None)
    )
    if effective_margin is not None:
        payload["margin_usdt"] = effective_margin

    def _apply_margin_mode_override(raw_value: Any) -> None:
        if not isinstance(raw_value, str):
            return
        token = raw_value.strip()
        if not token:
            return
        normalised = _normalise_margin_mode_token(token)
        if normalised == "isolated":
            payload["margin_mode"] = "ISOLATED"
        elif normalised == "cross":
            payload["margin_mode"] = "CROSSED"
        else:
            payload["margin_mode"] = token.upper()

    def _apply_margin_coin_override(raw_value: Any) -> None:
        if not isinstance(raw_value, str):
            return

        token = raw_value.strip()
        if not token:
            return

        # Ignore payloads that only contain digits. TradingView alerts encode the
        # margin amount as ``marginCoin = "5"`` which would otherwise override the
        # configured asset and break the BingX synchronisation calls.
        if not any(char.isalpha() for char in token):
            return

        payload["margin_coin"] = token.upper()

    def _apply_leverage_override(raw_value: Any) -> None:
        try:
            leverage_value = int(float(raw_value))
        except (TypeError, ValueError):
            return
        if leverage_value > 0:
            payload["leverage"] = leverage_value
            payload["leverage_override"] = leverage_value

    if position_side is None and not mapping_has_position:
        if reduce_only:
            position_side = "SHORT" if side == "BUY" else "LONG"
        else:
            position_side = "LONG" if side == "BUY" else "SHORT"

    payload["position_side"] = position_side
    payload["intent"] = _infer_intent(side, position_side, bool(reduce_only))

    if snapshot:
        _apply_margin_mode_override(
            snapshot.get("margin_mode")
            or snapshot.get("marginType")
        )
        _apply_margin_coin_override(
            snapshot.get("margin_coin")
            or snapshot.get("marginCoin")
            or snapshot.get("margin_asset")
            or snapshot.get("marginAsset")
        )
        _apply_leverage_override(snapshot.get("leverage"))

    # Margin- und Leverage-Defaults stammen aus dem gespeicherten Zustand.
    # TradingView-Signale dürfen Leverage nur über ein ``lev``-Feld überschreiben;
    # ohne Override werden die Werte aus ``state.json`` an BingX übermittelt.

    if price_value is not None and order_type != "MARKET":
        payload["price"] = price_value
    if reduce_only is not None:
        payload["reduce_only"] = reduce_only
    if client_order_id:
        payload["client_order_id"] = client_order_id

    return payload, None


async def _place_order_from_alert(
    application: Application,
    settings: Settings,
    alert: Mapping[str, Any],
    state_for_order: BotState,
    snapshot: Mapping[str, Any] | None,
    *,
    failure_label: str,
    success_heading: str,
    side_override: str | None = None,
    enforce_direction_rules: bool = True,
) -> bool:
    """Execute a BingX order derived from a TradingView alert."""

    dry_run_flag = _is_dry_run_enabled(settings, application)

    order_payload, error_message = _prepare_autotrade_order(
        alert,
        state_for_order,
        snapshot,
        settings=settings,
        side_override=side_override,
        enforce_direction_rules=enforce_direction_rules,
    )

    if error_message:
        message = error_message
        if failure_label != "Autotrade":
            message = message.replace("Autotrade", failure_label)
        if settings.telegram_chat_id:
            with contextlib.suppress(Exception):
                await application.bot.send_message(chat_id=settings.telegram_chat_id, text=message)
        LOGGER.info(error_message)
        return False

    assert order_payload is not None
    intent_token = order_payload.get("intent")

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
            recv_window=settings.bingx_recv_window,
        ) as client:
            side_token = order_payload["side"].upper()
            order_type = str(order_payload.get("order_type", "MARKET")).upper()
            limit_price = order_payload.get("price")
            tif_value = order_payload.get("time_in_force")

            executed = await place_signal_order(
                order_payload["symbol"],
                side_token,
                quantity=order_payload.get("quantity"),
                margin_usdt=order_payload.get("margin_usdt"),
                leverage=order_payload.get("leverage_override"),
                margin_mode=order_payload.get("margin_mode"),
                margin_coin=order_payload.get("margin_coin"),
                position_side=order_payload.get("position_side"),
                reduce_only=bool(order_payload.get("reduce_only")),
                client_order_id=order_payload.get("client_order_id"),
                order_type=order_type,
                price=limit_price,
                time_in_force=tif_value,
                symbol_meta=settings.symbol_meta,
                state_override=state_for_order,
                client_override=client,
                dry_run=dry_run_flag,
            )

            executed_payload = dict(executed.payload)
            if intent_token:
                executed_payload["intent"] = intent_token
            else:
                executed_payload["intent"] = _infer_intent(
                    executed_payload.get("side"),
                    executed_payload.get("position_side"),
                    bool(executed_payload.get("reduce_only")),
                )
            order_payload = executed_payload
    except BingXClientError as exc:
        LOGGER.error("%s order failed: %s", failure_label, exc)
        custom_message = _map_known_error_message(exc)
        message_text = custom_message or f"❌ {failure_label} fehlgeschlagen: {exc}"
        if settings.telegram_chat_id:
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    chat_id=settings.telegram_chat_id,
                    text=message_text,
                )
        return False

    if settings.telegram_chat_id:
        confirmation = _format_signal_confirmation(
            order_payload,
            auto_trade=failure_label.strip().lower() == "autotrade",
            timestamp=datetime.now(),
        )
        with contextlib.suppress(Exception):
            await application.bot.send_message(chat_id=settings.telegram_chat_id, text=confirmation)
    return True


def _format_signal_confirmation(
    order: Mapping[str, Any], *, auto_trade: bool, timestamp: datetime | None = None
) -> str:
    """Return the unified Telegram confirmation message for executed orders."""

    reduce_only = bool(order.get("reduce_only"))
    intent_token = str(order.get("intent") or "").upper()
    if not intent_token:
        intent_token = _infer_intent(
            order.get("side"),
            order.get("position_side"),
            reduce_only,
        )

    symbol = str(order.get("symbol") or "").strip() or "UNKNOWN"
    order_type_value = str(order.get("order_type") or "MARKET").strip() or "MARKET"
    order_type_display = order_type_value.title()

    position_side_value = str(order.get("position_side") or "").strip().upper()
    if not position_side_value:
        side_token = str(order.get("side") or "").strip().upper()
        if side_token == "BUY":
            position_side_value = "LONG"
        elif side_token == "SELL":
            position_side_value = "SHORT"
        else:
            position_side_value = "LONG"

    margin_value = order.get("margin_usdt")
    margin_float: float | None
    try:
        margin_float = float(margin_value) if margin_value is not None else None
    except (TypeError, ValueError):
        margin_float = None

    leverage_value = order.get("leverage")
    leverage_float: float | None
    try:
        leverage_float = float(leverage_value) if leverage_value is not None else None
    except (TypeError, ValueError):
        leverage_float = None

    quantity_value = order.get("quantity")
    quantity_text: str | None
    if quantity_value is None:
        quantity_text = None
    elif isinstance(quantity_value, (int, float)):
        quantity_text = format(float(quantity_value), "f").rstrip("0").rstrip(".") or "0"
    else:
        quantity_text = str(quantity_value)

    return build_signal_message(
        symbol=symbol,
        intent=intent_token,
        order_type=order_type_display,
        position_side=position_side_value,
        auto_trade=auto_trade,
        leverage=leverage_float,
        margin_usdt=margin_float,
        quantity=quantity_text,
        reduce_only=reduce_only,
        timestamp=timestamp,
    )


async def _execute_autotrade(
    application: Application, settings: Settings, alert: Mapping[str, Any]
) -> None:
    """Forward TradingView alerts as orders to BingX when enabled."""

    state_for_order, snapshot = _resolve_state_for_order(application)

    if not isinstance(state_for_order, BotState) or not state_for_order.autotrade_enabled:
        return

    await _place_order_from_alert(
        application,
        settings,
        alert,
        state_for_order,
        snapshot,
        failure_label="Autotrade",
        success_heading="🤖 Autotrade ausgeführt:",
        enforce_direction_rules=True,
    )


async def _manual_trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle manual trade button presses from TradingView alerts."""

    query = update.callback_query
    if not query or not context.application:
        return

    data = query.data or ""
    if not data.startswith("manual:"):
        await query.answer()
        return

    try:
        _, alert_id, side_token = data.split(":", 2)
    except ValueError:
        await query.answer()
        return

    side_token = side_token.lower()
    if side_token not in {"buy", "sell"}:
        await query.answer("Unbekannte Aktion.", show_alert=True)
        return

    alert = _get_manual_alert(context.application, alert_id)
    if alert is None:
        await query.answer("Signal nicht mehr verfügbar.", show_alert=True)
        return

    settings = _get_settings(context)
    if not settings:
        await query.answer("Einstellungen nicht geladen.", show_alert=True)
        return

    if not _bingx_credentials_available(settings):
        await query.answer("BingX API-Zugang fehlt für Trades.", show_alert=True)
        return

    state_for_order, snapshot = _resolve_state_for_order(context.application)
    if not isinstance(state_for_order, BotState):
        await query.answer("Bot-Zustand nicht verfügbar.", show_alert=True)
        return

    if state_for_order.autotrade_enabled:
        await query.answer("Autotrade ist aktiv – manueller Trade nicht notwendig.", show_alert=True)
        return

    side_override = "BUY" if side_token == "buy" else "SELL"

    await query.answer("Manueller Trade wird ausgeführt …")

    await _place_order_from_alert(
        context.application,
        settings,
        alert,
        state_for_order,
        snapshot,
        failure_label="Manueller Trade",
        success_heading="🛒 Manueller Trade ausgeführt:",
        side_override=side_override,
        enforce_direction_rules=False,
    )


async def _execute_manual_trade_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    request: ManualOrderRequest,
) -> None:
    if not update.message or context.application is None:
        return

    settings = _get_settings(context)
    if not settings:
        await update.message.reply_text("Einstellungen konnten nicht geladen werden.")
        return

    if not _bingx_credentials_available(settings):
        await update.message.reply_text("BingX API-Zugangsdaten fehlen für Trades.")
        return

    try:
        normalised_symbol = normalize_symbol(
            request.symbol, whitelist=settings.symbol_whitelist
        )
    except SymbolValidationError as exc:
        await update.message.reply_text(str(exc))
        return

    leverage_override = request.leverage
    if leverage_override is None and request.margin is not None:
        leverage_override = settings.default_leverage

    order_type = "LIMIT" if request.limit_price is not None else "MARKET"
    tif_value = request.time_in_force
    if order_type == "LIMIT" and not tif_value:
        tif_value = settings.default_time_in_force

    state_for_order, snapshot = _resolve_state_for_order(context.application)
    if state_for_order is None:
        state_for_order = _state_from_context(context)

    alert_payload: dict[str, Any] = {
        "symbol": normalised_symbol,
        "action": action,
        "order_type": order_type,
        "alert_id": f"telegram:{update.effective_chat.id if update.effective_chat else 'manual'}:{uuid.uuid4().hex}",
    }

    if request.quantity is not None:
        quantity_text = format(request.quantity, "f").rstrip("0").rstrip(".") or "0"
        alert_payload["qty"] = quantity_text

    if request.margin is not None:
        alert_payload["margin_usdt"] = request.margin

    if leverage_override is not None:
        alert_payload["lev"] = leverage_override

    if request.limit_price is not None:
        alert_payload["price"] = request.limit_price
    if tif_value is not None:
        alert_payload["tif"] = tif_value

    if request.reduce_only is not None:
        alert_payload["reduceOnly"] = request.reduce_only

    if request.client_order_id:
        alert_payload["clientOrderId"] = request.client_order_id

    success = await _place_order_from_alert(
        context.application,
        settings,
        alert_payload,
        state_for_order,
        snapshot,
        failure_label="Manueller Trade",
        success_heading="🛒 Manueller Trade ausgeführt:",
        enforce_direction_rules=False,
    )

    if success:
        await update.message.reply_text("✅ Order angenommen.")
    else:
        await update.message.reply_text("❌ Order konnte nicht ausgeführt werden.")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        request = _parse_manual_order_args(context.args or [], require_direction=True)
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    assert request.direction is not None
    action = _resolve_manual_action("open", request.direction)
    await _execute_manual_trade_command(
        update,
        context,
        action=action,
        request=request,
    )


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        request = _parse_manual_order_args(context.args or [], require_direction=True)
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    assert request.direction is not None
    action = _resolve_manual_action("close", request.direction)
    await _execute_manual_trade_command(
        update,
        context,
        action=action,
        request=request,
    )


async def _execute_hedge_quick_trade(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    direction: str,
    reduce_only: bool,
    tokens: Sequence[str] | None = None,
) -> None:
    if not update.message:
        return

    state = _state_from_context(context)
    if not state.global_trade.hedge_mode:
        await update.message.reply_text(
            "One-Way-Mode aktiv – nutze /mode hedge für getrennte LONG/SHORT-Befehle."
        )
        return

    try:
        trade_args = _parse_quick_trade_arguments(
            tokens if tokens is not None else (context.args or []),
            default_tif=state.global_trade.normalised_time_in_force(),
        )
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    if trade_args.quantity is None and state.global_trade.margin_usdt <= 0:
        await update.message.reply_text(GLOBAL_MARGIN_TOO_SMALL_MESSAGE)
        return

    try:
        action = _resolve_manual_action("close" if reduce_only else "open", direction)
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    request = _quick_trade_request_from_args(
        state,
        trade_args,
        reduce_only=reduce_only,
    )

    await _execute_manual_trade_command(
        update,
        context,
        action=action,
        request=request,
    )


async def long_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _execute_hedge_quick_trade(update, context, direction="LONG", reduce_only=False)


async def short_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _execute_hedge_quick_trade(update, context, direction="SHORT", reduce_only=False)


async def open_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []

    if state.global_trade.hedge_mode:
        await update.message.reply_text("Hedge-Mode aktiv – nutze /long oder /short.")
        return

    if args and args[0].strip().lower() in {"long", "short"}:
        await update.message.reply_text(
            "One-Way-Mode verwendet /open <Symbol> […]. Richtung ist nicht notwendig."
        )
        return

    trade_tokens = args

    try:
        trade_args = _parse_quick_trade_arguments(
            trade_tokens,
            default_tif=state.global_trade.normalised_time_in_force(),
        )
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    if trade_args.quantity is None and state.global_trade.margin_usdt <= 0:
        await update.message.reply_text(GLOBAL_MARGIN_TOO_SMALL_MESSAGE)
        return

    action = _resolve_manual_action("open", "LONG")

    request = _quick_trade_request_from_args(
        state,
        trade_args,
        reduce_only=False,
    )

    await _execute_manual_trade_command(
        update,
        context,
        action=action,
        request=request,
    )


async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    state = _state_from_context(context)
    args = context.args or []
    hedge_mode = bool(state.global_trade.hedge_mode)

    if hedge_mode:
        if not args:
            await update.message.reply_text(
                "Nutzung: /close long|short <Symbol> [--qty …] [--limit …] [--tif …]"
            )
            return
        direction_token = args[0].strip().upper()
        if direction_token not in {"LONG", "SHORT"}:
            await update.message.reply_text("Bitte LONG oder SHORT angeben.")
            return
        trade_tokens = args[1:]
        await _execute_hedge_quick_trade(
            update,
            context,
            direction=direction_token,
            reduce_only=True,
            tokens=trade_tokens,
        )
        return

    if args and args[0].strip().lower() in {"long", "short"}:
        await update.message.reply_text(
            "One-Way-Mode verwendet /close <Symbol> […]. Richtung ist nicht notwendig."
        )
        return

    trade_tokens = args

    try:
        trade_args = _parse_quick_trade_arguments(
            trade_tokens,
            default_tif=state.global_trade.normalised_time_in_force(),
        )
    except CommandUsageError as exc:
        await update.message.reply_text(exc.message)
        return

    if trade_args.quantity is None and state.global_trade.margin_usdt <= 0:
        await update.message.reply_text(GLOBAL_MARGIN_TOO_SMALL_MESSAGE)
        return

    action = _resolve_manual_action("close", "LONG")

    request = _quick_trade_request_from_args(
        state,
        trade_args,
        reduce_only=True,
    )

    await _execute_manual_trade_command(
        update,
        context,
        action=action,
        request=request,
    )


async def halt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if context.application is not None:
        context.application.bot_data["dry_run_override"] = True

    await update.message.reply_text("DRY_RUN=1 (keine Orders werden gesendet).")


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if context.application is not None:
        context.application.bot_data.pop("dry_run_override", None)

    await update.message.reply_text("DRY_RUN=0 (Orders werden wieder gesendet).")
async def _consume_tradingview_alerts(application: Application, settings: Settings) -> None:
    """Continuously consume TradingView alerts and forward them to Telegram."""

    queue = get_alert_queue()
    history = application.bot_data.setdefault("tradingview_alerts", deque(maxlen=20))
    assert isinstance(history, deque)

    while True:
        alert = await queue.get()
        try:
            if not isinstance(alert, Mapping):
                LOGGER.info("Received TradingView alert without mapping payload: %s", alert)
                continue

            history.append(alert)
            LOGGER.info("Stored TradingView alert for bot handlers")

            symbol = _extract_symbol_from_alert(alert)
            if symbol:
                _store_last_symbol(application, symbol)

            if settings.telegram_chat_id:
                try:
                    bot_state = application.bot_data.get("state")
                    state_obj = bot_state if isinstance(bot_state, BotState) else None
                    reply_markup = None
                    if (
                        state_obj
                        and not state_obj.autotrade_enabled
                        and _bingx_credentials_available(settings)
                    ):
                        alert_id = _store_manual_alert(application, alert)
                        reply_markup = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "🟢 Kaufen", callback_data=f"manual:{alert_id}:buy"
                                    ),
                                    InlineKeyboardButton(
                                        "🔴 Verkaufen", callback_data=f"manual:{alert_id}:sell"
                                    ),
                                ]
                            ]
                        )
                    await application.bot.send_message(
                        chat_id=settings.telegram_chat_id,
                        text=_format_tradingview_alert(alert, state_obj),
                        reply_markup=reply_markup,
                    )
                except Exception:  # pragma: no cover - network/Telegram errors
                    LOGGER.exception("Failed to send TradingView alert to Telegram chat %s", settings.telegram_chat_id)

            if _bingx_credentials_available(settings):
                await _execute_autotrade(application, settings, alert)
        finally:
            queue.task_done()


def _build_application(settings: Settings) -> Application:
    """Create and configure the Telegram application."""

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    state_file_exists = STATE_FILE.exists()
    state = load_state(STATE_FILE)
    if not isinstance(state, BotState):
        state = BotState()
    if not state_file_exists:
        _apply_settings_defaults_to_state(state, settings)
    try:
        export_state_snapshot(state)
    except Exception:  # pragma: no cover - filesystem issues are logged only
        LOGGER.exception("Failed to persist state snapshot to %s", STATE_SNAPSHOT_FILE)
    application.bot_data["state"] = state
    application.bot_data["state_file"] = STATE_FILE

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("positions", positions))
    application.add_handler(CommandHandler("margin", margin))
    application.add_handler(CommandHandler("lev", leverage))
    application.add_handler(CommandHandler("mode", mode))
    application.add_handler(CommandHandler("mgnmode", mgnmode))
    application.add_handler(CommandHandler("tif", tif))
    application.add_handler(CommandHandler("autotrade", autotrade))
    application.add_handler(CommandHandler("autotrade_direction", set_autotrade_direction))
    application.add_handler(CommandHandler("set_max_trade", set_max_trade))
    application.add_handler(CommandHandler("daily_report", daily_report))
    application.add_handler(CommandHandler("sync", sync))
    application.add_handler(CommandHandler("status_table", report))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("sell", sell))
    application.add_handler(CommandHandler("long", long_command))
    application.add_handler(CommandHandler("short", short_command))
    application.add_handler(CommandHandler("open", open_command))
    application.add_handler(CommandHandler("close", close_command))
    application.add_handler(CommandHandler("halt", halt))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CallbackQueryHandler(_manual_trade_callback, pattern=r"^manual:"))
    application.bot_data["settings"] = settings

    return application


async def _maybe_await(result: Any | Awaitable[Any] | None) -> Any | None:
    """Await *result* if it is awaitable and return the resolved value."""

    if inspect.isawaitable(result):
        return await result
    return result


async def _start_polling(application: Application) -> Callable[[], Awaitable[None]]:
    """Start polling using the best available API and return a stopper."""

    async def _noop() -> None:
        return None

    start_polling = getattr(application, "start_polling", None)
    if callable(start_polling):
        await _maybe_await(start_polling())

        stop_polling = getattr(application, "stop_polling", None)
        if callable(stop_polling):
            async def _stop_polling() -> None:
                await _maybe_await(stop_polling())

            return _stop_polling

        return _noop

    updater = getattr(application, "updater", None)
    if updater is not None:
        start_polling = getattr(updater, "start_polling", None)
        if callable(start_polling):
            await _maybe_await(start_polling())

            stop_polling = getattr(updater, "stop", None) or getattr(updater, "stop_polling", None)
            if callable(stop_polling):
                async def _stop_updater() -> None:
                    await _maybe_await(stop_polling())

                return _stop_updater

            return _noop

    run_polling = getattr(application, "run_polling", None)
    if callable(run_polling):
        result = run_polling()
        if inspect.isawaitable(result):
            await result
            return _noop

        raise RuntimeError(
            "telegram Application.run_polling() is not awaitable; "
            "unable to integrate with the async service loop."
        )

    raise RuntimeError("telegram Application does not expose a polling API")


async def run_bot(settings: Settings | None = None) -> None:
    """Run the Telegram bot until it is stopped."""

    settings = settings or get_settings()
    LOGGER.info("Starting Telegram bot polling loop")

    application = _build_application(settings)

    async with application:
        consumer_task: asyncio.Task[None] | None = None
        stop_polling: Callable[[], Awaitable[None]] | None = None

        try:
            await _maybe_await(application.start())

            await _register_bot_commands(application)

            state = application.bot_data.get("state")
            if isinstance(state, BotState):
                _schedule_daily_report(application, settings, state)

            if settings.tradingview_webhook_enabled:
                consumer_task = asyncio.create_task(
                    _consume_tradingview_alerts(application, settings)
                )

            if settings.telegram_chat_id:
                try:
                    await application.bot.send_message(
                        chat_id=settings.telegram_chat_id,
                        text="✅ Bot wurde gestartet und ist bereit.",
                    )
                except Exception:  # pragma: no cover - network/Telegram errors
                    LOGGER.exception(
                        "Failed to send startup notification to Telegram chat %s",
                        settings.telegram_chat_id,
                    )

            LOGGER.info("Bot connected. Listening for commands...")

            stop_polling = await _start_polling(application)

            await asyncio.Future()
        except (asyncio.CancelledError, KeyboardInterrupt):
            LOGGER.info("Shutdown requested. Stopping Telegram bot...")
        finally:
            if stop_polling is not None:
                with contextlib.suppress(Exception):
                    await stop_polling()

            with contextlib.suppress(Exception):
                await _maybe_await(application.stop())

            if consumer_task is not None:
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task

    LOGGER.info("Telegram bot stopped")


def main() -> None:
    """Entry point for running the Telegram bot via CLI."""

    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )

    try:
        settings = get_settings()
    except RuntimeError as error:
        LOGGER.error("Configuration error: %s", error)
        raise

    asyncio.run(run_bot(settings=settings))


if __name__ == "__main__":
    main()
