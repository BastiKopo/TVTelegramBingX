"""Telegram bot entry point for TVTelegramBingX."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Final

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import Settings, get_settings
from integrations.bingx_client import BingXClient, BingXClientError
from webhook.dispatcher import get_alert_queue

LOGGER: Final = logging.getLogger(__name__)


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


def _format_margin_payload(payload: Any) -> str:
    """Return a human readable string for margin data."""

    if isinstance(payload, Mapping):
        known_keys = (
            "availableMargin",
            "availableBalance",
            "margin",
            "usedMargin",
            "unrealizedPnL",
            "unrealizedProfit",
            "marginRatio",
        )
        lines = ["💰 Margin summary:"]
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
        lines = ["💰 Margin summary:"]
        for entry in payload:
            if isinstance(entry, Mapping):
                symbol = entry.get("symbol") or entry.get("currency") or entry.get("asset") or "Unknown"
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
        return "\n".join(lines)

    return "💰 Margin data: " + str(payload)


def _format_tradingview_alert(alert: Mapping[str, Any]) -> str:
    """Return a readable representation of a TradingView alert."""

    lines = ["📢 TradingView alert received!"]

    message = None
    for key in ("message", "alert", "text", "body"):
        value = alert.get(key) if isinstance(alert, Mapping) else None
        if value:
            message = str(value)
            break

    if message:
        lines.append(message)

    ticker = alert.get("ticker") if isinstance(alert, Mapping) else None
    price = alert.get("price") if isinstance(alert, Mapping) else None
    if ticker:
        extra = f"Ticker: {ticker}"
        if price is not None:
            extra += f" | Price: {_format_number(price)}"
        lines.append(extra)

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
            return "📈 No open positions found."
        return "📈 Open positions:\n" + "\n".join(lines)

    if isinstance(payload, Mapping):
        return "📈 Open positions:\n" + "\n".join(
            f"• {_humanize_key(str(key))}: {_format_number(value)}" for key, value in payload.items()
        )

    return "📈 Open positions: " + str(payload)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a simple status message."""

    if not update.message:
        return

    await update.message.reply_text("✅ Bot is running. Use /report, /margin or /leverage to query BingX once credentials are configured.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide helpful information to the user."""

    if not update.message:
        return

    await update.message.reply_text(
        "Available commands:\n"
        "/status - Check whether the bot is online.\n"
        "/report - Show BingX balance and open positions.\n"
        "/margin - Display current margin usage.\n"
        "/leverage - Display leverage for open positions."
    )


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

    try:
        async with BingXClient(
            api_key=settings.bingx_api_key or "",
            api_secret=settings.bingx_api_secret or "",
            base_url=settings.bingx_base_url,
        ) as client:
            balance = await client.get_account_balance()
            positions = await client.get_open_positions()
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to contact BingX: {exc}")
        return

    lines = ["📊 BingX account report:"]
    if isinstance(balance, Mapping):
        equity = balance.get("equity") or balance.get("totalEquity") or balance.get("balance")
        available = balance.get("availableMargin") or balance.get("availableBalance")
        pnl = balance.get("unrealizedPnL") or balance.get("unrealizedProfit")
        if equity is not None:
            lines.append(f"• Equity: {_format_number(equity)}")
        if available is not None:
            lines.append(f"• Available: {_format_number(available)}")
        if pnl is not None:
            lines.append(f"• Unrealized PnL: {_format_number(pnl)}")
        if len(lines) == 1:
            for key, value in balance.items():
                lines.append(f"• {key}: {_format_number(value)}")
    else:
        lines.append(f"• Balance: {balance}")

    lines.append("")
    lines.append(_format_positions_payload(positions))

    await update.message.reply_text("\n".join(lines))


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return margin information from BingX."""

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
            data = await client.get_margin_summary()
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch margin information: {exc}")
        return

    await update.message.reply_text(_format_margin_payload(data))


async def leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return leverage information for the account's open positions."""

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
            leverage_data = await client.get_leverage_settings()
            positions = await client.get_open_positions()
    except BingXClientError as exc:
        await update.message.reply_text(f"❌ Failed to fetch leverage information: {exc}")
        return

    message_lines = ["📈 Leverage overview:"]

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

            if settings.telegram_chat_id:
                try:
                    await application.bot.send_message(
                        chat_id=settings.telegram_chat_id,
                        text=_format_tradingview_alert(alert),
                    )
                except Exception:  # pragma: no cover - network/Telegram errors
                    LOGGER.exception("Failed to send TradingView alert to Telegram chat %s", settings.telegram_chat_id)
        finally:
            queue.task_done()


def _build_application(settings: Settings) -> Application:
    """Create and configure the Telegram application."""

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("margin", margin))
    application.add_handler(CommandHandler("leverage", leverage))
    application.bot_data["settings"] = settings

    return application


async def run_bot(settings: Settings | None = None) -> None:
    """Run the Telegram bot until it is stopped."""

    settings = settings or get_settings()
    LOGGER.info("Starting Telegram bot polling loop")

    application = _build_application(settings)

    async with application:
        stop_event = asyncio.Event()
        consumer_task: asyncio.Task[None] | None = None
        try:
            await application.start()
            if settings.tradingview_webhook_enabled:
                consumer_task = application.create_task(
                    _consume_tradingview_alerts(application, settings)
                )

            await application.updater.start_polling()

            LOGGER.info("Bot connected. Listening for commands...")

            await stop_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            LOGGER.info("Shutdown requested. Stopping Telegram bot...")
        finally:
            if consumer_task is not None:
                consumer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer_task
            await application.stop()

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
