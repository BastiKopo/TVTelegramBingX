"""Async entrypoint for running the Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
try:  # pragma: no cover - fallback for tests without aiogram installed
    from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
except Exception:  # pragma: no cover - fallback definitions
    class TelegramAPIError(Exception):
        """Fallback base error when aiogram exceptions are unavailable."""

    class TelegramForbiddenError(TelegramAPIError):
        """Fallback forbidden error when aiogram exceptions are unavailable."""

from .backend_client import BackendClient
from .config import BotSettings, get_settings
from .handlers import BotHandlers, build_router
from .middleware import AdminMiddleware
from .metrics import start_metrics_server
from .models import BotState

logger = logging.getLogger(__name__)


async def _setup_dispatcher(settings: BotSettings, client: BackendClient) -> Dispatcher:
    dispatcher = Dispatcher()
    handlers = BotHandlers(client, settings)
    router = build_router(handlers)
    dispatcher.include_router(router)
    dispatcher.message.middleware(AdminMiddleware(settings.admin_ids))
    dispatcher.callback_query.middleware(AdminMiddleware(settings.admin_ids))
    return dispatcher


def _format_startup_message(state: BotState) -> str:
    """Return a human readable status summary for startup notifications."""

    auto_trade_status = "aktiviert" if state.auto_trade_enabled else "deaktiviert"
    confirmation_status = (
        "erforderlich" if state.manual_confirmation_required else "optional"
    )
    return (
        "🤖 Bot gestartet\n"
        f"• Automatischer Handel: {auto_trade_status}\n"
        f"• Bestätigung: {confirmation_status}\n"
        f"• Margin-Modus: {state.margin_mode}\n"
        f"• Hebel: {state.leverage}x"
    )


async def _announce_startup(bot: Bot, client: BackendClient, settings: BotSettings) -> None:
    """Fetch the current state and broadcast it to configured recipients."""

    try:
        state = await client.get_state()
    except Exception:  # pragma: no cover - defensive guard
        logger.exception("Unable to fetch bot state during startup")
        message = "🤖 Bot gestartet, Status konnte nicht geladen werden."
    else:
        message = _format_startup_message(state)

    recipients = set(settings.admin_ids)
    if settings.broadcast_chat_id is not None:
        recipients.add(settings.broadcast_chat_id)

    for chat_id in recipients:
        try:
            await bot.send_message(chat_id, message)
        except TelegramForbiddenError:
            logger.warning(
                "Startup notification forbidden for chat", extra={"chat_id": chat_id}
            )
        except TelegramAPIError:
            logger.exception(
                "Failed to deliver startup notification", extra={"chat_id": chat_id}
            )


async def main() -> None:
    settings = get_settings()
    from .telemetry import configure_bot_telemetry  # Local import to avoid test dependency
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    configure_bot_telemetry(settings)
    if settings.metrics_enabled:
        try:
            start_metrics_server(settings.metrics_host, settings.metrics_port)
            logger.info(
                "Bot metrics exporter started",
                extra={"host": settings.metrics_host, "port": settings.metrics_port},
            )
        except RuntimeError as exc:
            logger.warning("Unable to start Prometheus metrics server: %s", exc)
    client = BackendClient(settings.backend_base_url, timeout=settings.request_timeout)
    dispatcher = await _setup_dispatcher(settings, client)
    bot = Bot(token=settings.telegram_bot_token, parse_mode=ParseMode.HTML)
    logger.info("Starting Telegram bot", extra={"admins": list(settings.admin_ids)})
    await _announce_startup(bot, client, settings)
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    asyncio.run(main())
