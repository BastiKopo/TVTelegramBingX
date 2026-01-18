from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

import uvicorn

from tvtelegrambingx.ai.autonomous import run_ai_autonomous
from tvtelegrambingx.bot.dynamic_tp_monitor import monitor_dynamic_tp
from tvtelegrambingx.bot.stop_loss_monitor import monitor_stop_loss
from tvtelegrambingx.bot.telegram_bot import configure as configure_telegram
from tvtelegrambingx.bot.telegram_bot import run_telegram_bot
from tvtelegrambingx.config import load_settings
from tvtelegrambingx.integrations.bingx_account import configure as configure_account
from tvtelegrambingx.webhook.server import app as webhook_app

LOGGER = logging.getLogger(__name__)


async def _run_webhook(settings) -> None:
    if settings.tradingview_ssl_certfile and not settings.tradingview_ssl_keyfile:
        raise RuntimeError(
            "TRADINGVIEW_WEBHOOK_SSL_KEYFILE is required when TRADINGVIEW_WEBHOOK_SSL_CERTFILE is set"
        )
    if settings.tradingview_ssl_keyfile and not settings.tradingview_ssl_certfile:
        raise RuntimeError(
            "TRADINGVIEW_WEBHOOK_SSL_CERTFILE is required when TRADINGVIEW_WEBHOOK_SSL_KEYFILE is set"
        )

    config = uvicorn.Config(
        webhook_app,
        host=settings.tradingview_host,
        port=settings.tradingview_port,
        log_level="info",
        ssl_certfile=settings.tradingview_ssl_certfile,
        ssl_keyfile=settings.tradingview_ssl_keyfile,
        ssl_ca_certs=settings.tradingview_ssl_ca_certs,
    )
    server = uvicorn.Server(config)
    scheme = "https" if settings.tradingview_ssl_certfile else "http"
    LOGGER.info(
        "Starting TradingView webhook on %s://%s:%s",
        scheme,
        settings.tradingview_host,
        settings.tradingview_port,
    )
    await server.serve()


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    settings = load_settings()
    configure_account(settings)
    configure_ai(settings)
    configure_telegram(settings)

    tasks = [asyncio.create_task(run_telegram_bot(settings), name="telegram-bot")]
    tasks.append(asyncio.create_task(monitor_dynamic_tp(settings), name="dynamic-tp"))
    tasks.append(asyncio.create_task(monitor_stop_loss(settings), name="stop-loss"))
    tasks.append(asyncio.create_task(run_ai_autonomous(settings), name="ai-autonomous"))
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
