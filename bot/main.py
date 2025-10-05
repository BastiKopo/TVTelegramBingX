"""Async entrypoint for running the Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from .backend_client import BackendClient
from .config import BotSettings, get_settings
from .handlers import BotHandlers, build_router
from .middleware import AdminMiddleware

logger = logging.getLogger(__name__)


async def _setup_dispatcher(settings: BotSettings, client: BackendClient) -> Dispatcher:
    dispatcher = Dispatcher()
    handlers = BotHandlers(client, settings)
    router = build_router(handlers)
    dispatcher.include_router(router)
    dispatcher.message.middleware(AdminMiddleware(settings.admin_ids))
    dispatcher.callback_query.middleware(AdminMiddleware(settings.admin_ids))
    return dispatcher


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = BackendClient(settings.backend_base_url, timeout=settings.request_timeout)
    dispatcher = await _setup_dispatcher(settings, client)
    bot = Bot(token=settings.telegram_bot_token, parse_mode=ParseMode.HTML)
    logger.info("Starting Telegram bot", extra={"admins": list(settings.admin_ids)})
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    asyncio.run(main())
