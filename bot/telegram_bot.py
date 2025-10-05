"""Telegram bot entry point for TVTelegramBingX."""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from config import Settings, get_settings

LOGGER: Final = logging.getLogger(__name__)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with a simple status message."""

    if not update.message:
        return

    await update.message.reply_text("✅ Bot is running. BingX integration coming soon.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide helpful information to the user."""

    if not update.message:
        return

    await update.message.reply_text(
        "Available commands:\n"
        "/status - Check whether the bot is online.\n"
        "/report - Placeholder for trade reports.\n"
        "/margin - Placeholder for margin information.\n"
        "/leverage - Placeholder for leverage settings."
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return placeholder report information."""

    if not update.message:
        return

    await update.message.reply_text(
        "📊 Reports are not available yet. BingX integration is under development."
    )


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return placeholder margin information."""

    if not update.message:
        return

    await update.message.reply_text(
        "💰 Margin data is currently unavailable. Check back after BingX integration."
    )


async def leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return placeholder leverage information."""

    if not update.message:
        return

    await update.message.reply_text(
        "📈 Leverage details will be displayed once BingX integration is ready."
    )


def _build_application(settings: Settings) -> Application:
    """Create and configure the Telegram application."""

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("margin", margin))
    application.add_handler(CommandHandler("leverage", leverage))

    return application


async def run_bot(settings: Settings | None = None) -> None:
    """Run the Telegram bot until it is stopped."""

    settings = settings or get_settings()
    LOGGER.info("Starting Telegram bot polling loop")

    application = _build_application(settings)

    LOGGER.info("Bot connected. Listening for commands...")
    await application.initialize()
    await application.start()

    try:
        await application.updater.start_polling()
        await application.updater.idle()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
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
