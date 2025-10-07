"""Telegram bot entry point for TVTelegramBingX."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import re
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, time
from pathlib import Path
from typing import Any, Final

from telegram import BotCommand, ReplyKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import Settings, get_settings
from integrations.bingx_client import BingXClient, BingXClientError
from webhook.dispatcher import get_alert_queue

from .state import (
    BotState,
    export_state_snapshot,
    load_state,
    load_state_snapshot,
    save_state,
    STATE_EXPORT_FILE,
)

LOGGER: Final = logging.getLogger(__name__)

STATE_FILE: Final = Path("bot_state.json")
STATE_SNAPSHOT_FILE: Final = STATE_EXPORT_FILE
MAIN_KEYBOARD: Final = ReplyKeyboardMarkup(
    [
        ["/start", "/stop", "/status"],
        ["/report", "/positions", "/sync"],
    ],
    resize_keyboard=True,
)


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


def _normalise_symbol(value: str) -> str:
    """Return an uppercase trading symbol without broker prefixes."""

    text = value.strip().upper()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


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
        "Diese Werte werden für alle Futures-Trades verwendet. Passe sie mit /margin <Modus> oder /leverage <Wert> an."
    )

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
        BotCommand("report", "BingX Kontoübersicht"),
        BotCommand("positions", "Offene Positionen anzeigen"),
        BotCommand("margin", "Margin anzeigen oder setzen"),
        BotCommand("leverage", "Leverage anzeigen oder setzen"),
        BotCommand("autotrade", "Autotrade an/aus"),
        BotCommand("autotrade_direction", "Autotrade Richtung"),
        BotCommand("set_max_trade", "Max. Tradegröße setzen"),
        BotCommand("daily_report", "Daily Report Zeit"),
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


def _bingx_credentials_available(settings: Settings | None) -> bool:
    """Return ``True`` when BingX credentials are configured."""

    return bool(settings and settings.bingx_api_key and settings.bingx_api_secret)


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


def _format_tradingview_alert(alert: Mapping[str, Any]) -> str:
    """Return a readable representation of a TradingView alert."""

    if not isinstance(alert, Mapping):
        return "📢 TradingView Signal\n" + str(alert)

    strategy_data = alert.get("strategy")
    strategy = strategy_data if isinstance(strategy_data, Mapping) else {}

    lines = ["📢 TradingView Signal"]

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
    if symbol:
        extra_lines.append(f"• Paar: {symbol}")
    if side_display:
        extra_lines.append(f"• Richtung: {side_display}")
    if quantity_value is not None:
        extra_lines.append(f"• Menge: {_format_number(quantity_value)}")
    if price_value is not None:
        extra_lines.append(f"• Preis: {_format_number(price_value)}")
    if timeframe:
        extra_lines.append(f"• Timeframe: {timeframe}")

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
    autotrade = "🟢 aktiviert" if state.autotrade_enabled else "🔴 deaktiviert"
    direction_map = {
        "long": "Nur Long",
        "short": "Nur Short",
        "both": "Long & Short",
    }
    autotrade_direction = direction_map.get(state.normalised_autotrade_direction(), "Long & Short")
    margin_mode = state.normalised_margin_mode()
    margin_coin = state.normalised_margin_asset()
    margin_summary = (
        f"{margin_mode} ({margin_coin})" if margin_coin else margin_mode
    )
    leverage = f"{state.leverage:g}x"
    max_trade = (
        f"{_format_number(state.max_trade_size)}" if state.max_trade_size is not None else "nicht gesetzt"
    )
    daily_report = state.daily_report_time or "deaktiviert"

    await update.message.reply_text(
        "\n".join(
            [
                "✅ Bot läuft und ist erreichbar.",
                f"• Autotrade: {autotrade}",
                f"• Signale: {autotrade_direction}",
                f"• Margin: {margin_summary}",
                f"• Leverage: {leverage}",
                f"• Max. Trade-Größe: {max_trade}",
                f"• Daily Report: {daily_report}",
                "Nutze /help für alle Befehle.",
            ]
        ),
        reply_markup=MAIN_KEYBOARD,
    )


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
        "/margin [Symbol] <cross|isolated> [Coin] - Margin anzeigen oder setzen.\n"
        "/leverage [Symbol] <Wert> [Coin] - Leverage anzeigen oder setzen.\n"
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
        ) as client:
            data = await client.get_open_positions()
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch positions: {exc}")
        return

    await update.message.reply_text(_format_positions_payload(data))


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return margin information from BingX."""

    if not update.message:
        return

    state = _state_from_context(context)

    args = context.args or []
    symbol_override: str | None = None

    if args:
        try:
            parsed = _parse_margin_command_args(
                args,
                default_mode=state.margin_mode,
                default_coin=state.margin_asset,
            )
        except CommandUsageError as exc:
            first_arg = args[0] if args else ""
            if len(args) > 1 or not _looks_like_symbol(first_arg) or _normalise_margin_mode_token(first_arg):
                await update.message.reply_text(exc.message)
                return
            symbol_override = _normalise_symbol(first_arg)
        else:
            await _apply_margin_update(update, context, parsed)
            return
    else:
        await update.message.reply_text(_format_futures_settings_summary(state))
        return

    settings = _get_settings(context)
    if not _bingx_credentials_available(settings):
        await update.message.reply_text(
            "⚠️ BingX API credentials are not configured. Set BINGX_API_KEY and BINGX_API_SECRET to enable this command."
        )
        return

    assert settings

    if symbol_override is not None:
        symbol = symbol_override
        provided = True
    else:
        symbol, provided = _resolve_symbol_argument(context)

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
        ) as client:
            try:
                data = await client.get_margin_summary(symbol=symbol)
            except BingXClientError as exc:
                message = str(exc).lower()
                if symbol is None and _is_symbol_required_error(exc):
                    positions = await client.get_open_positions()
                    inferred = _infer_symbol_from_positions(positions)
                    if inferred:
                        symbol = inferred
                        data = await client.get_margin_summary(symbol=inferred)
                    else:
                        await update.message.reply_text(
                            "⚠️ Die BingX API verlangt ein Symbol. Beispiel: /margin BTCUSDT",
                        )
                        return
                elif "100400" in message and "api" in message and "not exist" in message:
                    await update.message.reply_text(
                        "⚠️ Diese Margin-API ist für dein BingX-Konto nicht verfügbar.",
                    )
                    return
                else:
                    await update.message.reply_text(f"❌ Failed to fetch margin information: {exc}")
                    return
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch margin information: {exc}")
        return

    if symbol and (provided or state.last_symbol != symbol):
        state.last_symbol = symbol
        _persist_state(context)

    message = _format_margin_payload(data)
    if symbol and symbol not in message:
        message += f"\n(Symbol: {symbol})"

    await update.message.reply_text(message)


async def leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return leverage information for the account's open positions."""

    if not update.message:
        return

    state = _state_from_context(context)

    args = context.args or []
    symbol_override: str | None = None

    if args:
        try:
            parsed = _parse_leverage_command_args(
                args,
                default_mode=state.margin_mode,
                default_coin=state.margin_asset,
            )
        except CommandUsageError as exc:
            first_arg = args[0] if args else ""
            if len(args) > 1 or not _looks_like_symbol(first_arg) or _normalise_margin_mode_token(first_arg):
                await update.message.reply_text(exc.message)
                return
            symbol_override = _normalise_symbol(first_arg)
        else:
            await _apply_leverage_update(update, context, parsed)
            return
    else:
        await update.message.reply_text(_format_futures_settings_summary(state))
        return

    settings = _get_settings(context)
    if not _bingx_credentials_available(settings):
        await update.message.reply_text(
            "⚠️ BingX API credentials are not configured. Set BINGX_API_KEY and BINGX_API_SECRET to enable this command."
        )
        return

    assert settings

    if symbol_override is not None:
        symbol = symbol_override
        provided = True
    else:
        symbol, provided = _resolve_symbol_argument(context)

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
        ) as client:
            positions: Any | None = None
            try:
                leverage_data = await client.get_leverage_settings(symbol=symbol)
            except BingXClientError as exc:
                if symbol is None and _is_symbol_required_error(exc):
                    positions = await client.get_open_positions()
                    inferred = _infer_symbol_from_positions(positions)
                    if inferred:
                        symbol = inferred
                        leverage_data = await client.get_leverage_settings(symbol=inferred)
                    else:
                        await update.message.reply_text(
                            "⚠️ Die BingX API verlangt ein Symbol. Beispiel: /leverage BTCUSDT",
                        )
                        return
                else:
                    await update.message.reply_text(f"❌ Failed to fetch leverage information: {exc}")
                    return

            if positions is None:
                positions = await client.get_open_positions(symbol=symbol)
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch leverage information: {exc}")
        return

    if symbol and (provided or state.last_symbol != symbol):
        state.last_symbol = symbol
        _persist_state(context)

    header = "📈 Leverage overview"
    if symbol:
        header += f" ({symbol})"
    header += ":"

    message_lines = [header]

    if isinstance(leverage_data, Mapping):
        for key, value in leverage_data.items():
            message_lines.append(f"• {key}: {_format_number(value)}")
    elif isinstance(leverage_data, Sequence):
        for entry in leverage_data:
            if isinstance(entry, Mapping):
                symbol = entry.get("symbol") or entry.get("pair") or "Unknown"
                leverage = entry.get("leverage") or entry.get("maxLeverage")
                message_lines.append(f"• {symbol}: {_format_number(leverage)}x")
            else:
                message_lines.append(f"• {entry}")
    elif leverage_data is not None:
        message_lines.append(f"• {leverage_data}")

    if message_lines and len(message_lines) == 1:
        message_lines.append("• No leverage data returned by the API.")

    if positions:
        message_lines.append("")
        message_lines.append(_format_positions_payload(positions))

    await update.message.reply_text("\n".join(message_lines))


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


def _prepare_autotrade_order(
    alert: Mapping[str, Any],
    state: BotState,
    snapshot: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the BingX order payload for an alert or a failure reason."""

    symbol = _extract_symbol_from_alert(alert) or ""
    if not symbol:
        return None, "⚠️ Autotrade übersprungen: Kein Symbol im Signal gefunden."

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

    if quantity_raw is None:
        if state.max_trade_size is None:
            return None, "⚠️ Autotrade übersprungen: Keine Positionsgröße angegeben und kein Limit gesetzt."
        quantity_value = state.max_trade_size
    else:
        try:
            quantity_value = float(quantity_raw)
        except (TypeError, ValueError):
            return None, "⚠️ Autotrade übersprungen: Positionsgröße konnte nicht interpretiert werden."

    if quantity_value <= 0:
        return None, "⚠️ Autotrade übersprungen: Positionsgröße muss größer als 0 sein."

    if state.max_trade_size is not None and quantity_value > state.max_trade_size:
        quantity_value = state.max_trade_size

    price_raw = alert.get("orderPrice") or alert.get("price")
    price_value: float | None
    if price_raw is None:
        price_value = None
    else:
        try:
            price_value = float(price_raw)
        except (TypeError, ValueError):
            price_value = None

    order_type = str(alert.get("orderType") or alert.get("type") or "MARKET").upper()

    reduce_only = _bool_from_value(
        alert.get("reduceOnly")
        or alert.get("reduce_only")
        or alert.get("closePosition")
    )

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

    client_order_id_raw = (
        alert.get("clientOrderId")
        or alert.get("client_id")
        or alert.get("id")
    )
    client_order_id = str(client_order_id_raw).strip() if client_order_id_raw else None

    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity_value,
        "order_type": order_type,
        "margin_mode": state.normalised_margin_mode(),
        "leverage": state.leverage,
        "margin_coin": state.normalised_margin_asset(),
    }

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
        if isinstance(raw_value, str) and raw_value.strip():
            payload["margin_coin"] = raw_value.strip().upper()

    def _apply_leverage_override(raw_value: Any) -> None:
        try:
            leverage_value = float(raw_value)
        except (TypeError, ValueError):
            return
        if leverage_value > 0:
            payload["leverage"] = leverage_value

    if position_side is None:
        if reduce_only:
            position_side = "SHORT" if side == "BUY" else "LONG"
        else:
            position_side = "LONG" if side == "BUY" else "SHORT"

    payload["position_side"] = position_side

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

    _apply_margin_mode_override(
        alert.get("margin_mode")
        or alert.get("marginMode")
        or alert.get("margin_type")
        or alert.get("marginType")
    )
    _apply_margin_coin_override(
        alert.get("margin_coin")
        or alert.get("marginCoin")
        or alert.get("margin_asset")
        or alert.get("marginAsset")
    )
    _apply_leverage_override(
        alert.get("leverage")
        or alert.get("leverage_value")
        or alert.get("leverageValue")
    )

    if price_value is not None and order_type != "MARKET":
        payload["price"] = price_value
    if reduce_only is not None:
        payload["reduce_only"] = reduce_only
    if client_order_id:
        payload["client_order_id"] = client_order_id

    return payload, None


def _format_autotrade_confirmation(order: Mapping[str, Any], response: Any) -> str:
    """Return a user-facing confirmation message for executed autotrades."""

    lines = ["🤖 Autotrade ausgeführt:"]
    lines.append(
        "• "
        + " ".join(
            [
                str(order.get("side", "")),
                str(order.get("symbol", "")),
                f"{_format_number(order.get('quantity', 0))}",
            ]
        )
    )
    leverage = order.get("leverage")
    price = order.get("price")
    extra_parts = [order.get("order_type", "MARKET")] if order.get("order_type") else []
    if price is not None:
        extra_parts.append(f"Preis {_format_number(price)}")
    if leverage:
        extra_parts.append(f"Leverage {_format_number(leverage)}x")
    margin_coin = order.get("margin_coin")
    if margin_coin:
        extra_parts.append(f"Margin {margin_coin}")
    if extra_parts:
        lines.append("• " + " | ".join(extra_parts))

    if isinstance(response, Mapping):
        order_id = response.get("orderId") or response.get("order_id") or response.get("id")
        status = response.get("status") or response.get("orderStatus")
        if order_id:
            lines.append(f"• Order ID: {order_id}")
        if status:
            lines.append(f"• Status: {status}")

    return "\n".join(lines)


async def _execute_autotrade(
    application: Application, settings: Settings, alert: Mapping[str, Any]
) -> None:
    """Forward TradingView alerts as orders to BingX when enabled."""

    state_in_memory = application.bot_data.get("state")
    state_file = Path(application.bot_data.get("state_file", STATE_FILE))

    persisted_state = load_state(state_file)
    if not isinstance(state_in_memory, BotState):
        state_in_memory = persisted_state
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

    state_for_order = (
        BotState.from_mapping(merged_state_data)
        if merged_state_data
        else (state_in_memory if isinstance(state_in_memory, BotState) else persisted_state)
    )

    if not isinstance(state_for_order, BotState) or not state_for_order.autotrade_enabled:
        return

    order_payload, error_message = _prepare_autotrade_order(alert, state_for_order, snapshot)
    if error_message:
        if settings.telegram_chat_id:
            with contextlib.suppress(Exception):
                await application.bot.send_message(chat_id=settings.telegram_chat_id, text=error_message)
        LOGGER.info(error_message)
        return

    assert order_payload is not None

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
        ) as client:
            margin_mode = order_payload.get("margin_mode")
            margin_coin = order_payload.get("margin_coin")
            leverage_value = order_payload.get("leverage")

            if margin_mode:
                try:
                    await client.set_margin_type(
                        symbol=order_payload["symbol"],
                        margin_mode=margin_mode,
                        margin_coin=margin_coin,
                    )
                except BingXClientError as exc:
                    LOGGER.warning(
                        "Failed to synchronise margin configuration for %s: %s",
                        order_payload["symbol"],
                        exc,
                    )

            if leverage_value is not None:
                try:
                    await client.set_leverage(
                        symbol=order_payload["symbol"],
                        leverage=leverage_value,
                        margin_mode=margin_mode,
                        margin_coin=margin_coin,
                    )
                except BingXClientError as exc:
                    LOGGER.warning(
                        "Failed to synchronise leverage for %s: %s",
                        order_payload["symbol"],
                        exc,
                    )

            response = await client.place_order(
                symbol=order_payload["symbol"],
                side=order_payload["side"],
                position_side=order_payload.get("position_side"),
                quantity=order_payload["quantity"],
                order_type=order_payload.get("order_type", "MARKET"),
                price=order_payload.get("price"),
                margin_mode=order_payload.get("margin_mode"),
                margin_coin=order_payload.get("margin_coin"),
                leverage=order_payload.get("leverage"),
                reduce_only=order_payload.get("reduce_only"),
                client_order_id=order_payload.get("client_order_id"),
            )
    except BingXClientError as exc:
        LOGGER.error("Autotrade order failed: %s", exc)
        if settings.telegram_chat_id:
            with contextlib.suppress(Exception):
                await application.bot.send_message(
                    chat_id=settings.telegram_chat_id,
                    text=f"❌ Autotrade fehlgeschlagen: {exc}",
                )
        return

    if settings.telegram_chat_id:
        confirmation = _format_autotrade_confirmation(order_payload, response)
        with contextlib.suppress(Exception):
            await application.bot.send_message(chat_id=settings.telegram_chat_id, text=confirmation)
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
                    await application.bot.send_message(
                        chat_id=settings.telegram_chat_id,
                        text=_format_tradingview_alert(alert),
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

    state = load_state(STATE_FILE)
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
    application.add_handler(CommandHandler("leverage", leverage))
    application.add_handler(CommandHandler("autotrade", autotrade))
    application.add_handler(CommandHandler("autotrade_direction", set_autotrade_direction))
    application.add_handler(CommandHandler("set_max_trade", set_max_trade))
    application.add_handler(CommandHandler("daily_report", daily_report))
    application.add_handler(CommandHandler("sync", sync))
    application.add_handler(CommandHandler("status_table", report))
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
