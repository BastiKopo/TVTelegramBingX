"""Entry point for the TVTelegramBingX application."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import uvicorn

from tvtelegrambingx.bot.telegram_bot import configure as configure_telegram
from tvtelegrambingx.bot.telegram_bot import run_telegram_bot
from tvtelegrambingx.config import load_settings
from tvtelegrambingx.integrations.bingx_client import configure
from tvtelegrambingx.webhook.server import build_app

LOGGER = logging.getLogger(__name__)


async def _run_webhook(settings) -> None:
    app = build_app(settings)
    config = uvicorn.Config(app, host=settings.tradingview_host, port=settings.tradingview_port, log_level="info")
    server = uvicorn.Server(config)
    LOGGER.info("Starting TradingView webhook on %s:%s", settings.tradingview_host, settings.tradingview_port)
    await server.serve()


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    settings = load_settings()
    configure(settings)
    configure_telegram(settings)

    tasks = [asyncio.create_task(run_telegram_bot(settings), name="telegram-bot")]
    if settings.tradingview_webhook_enabled:
        tasks.append(asyncio.create_task(_run_webhook(settings), name="webhook-server"))

    def _log_task_result(task: asyncio.Task) -> None:
        if task.cancelled():
            LOGGER.info("Task %s cancelled", task.get_name())
        elif exc := task.exception():
            LOGGER.error("Task %s exited with error", task.get_name(), exc_info=exc)
        else:
            LOGGER.info("Task %s finished", task.get_name())

    for task in tasks:
        task.add_done_callback(_log_task_result)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


def main() -> None:
    with suppress(KeyboardInterrupt):
        asyncio.run(amain())


if __name__ == "__main__":
    main()
