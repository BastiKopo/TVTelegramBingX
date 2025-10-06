"""Unified application entry point for the Telegram bot and webhook server."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import re
import signal

import uvicorn

from bot.telegram_bot import run_bot
from config import Settings, get_settings
from webhook.server import create_app

LOGGER = logging.getLogger(__name__)


def _resolve_webhook_binding() -> tuple[str, int]:
    """Return the host/port configuration for the webhook server."""

    host = os.getenv("TRADINGVIEW_WEBHOOK_HOST", "0.0.0.0")
    port_raw = os.getenv("TRADINGVIEW_WEBHOOK_PORT", "8443")
    try:
        port = int(port_raw)
    except ValueError as exc:  # pragma: no cover - misconfiguration guard
        raise RuntimeError(
            "Invalid TRADINGVIEW_WEBHOOK_PORT value. Provide a valid integer."
        ) from exc
    return host, port


UVICORN_MIN_VERSION = (0, 20, 0)


def _is_uvicorn_compatible(version_raw: str, minimum: tuple[int, ...]) -> bool:
    """Return ``True`` when the installed uvicorn version satisfies ``minimum``."""

    parts = [int(part) for part in re.findall(r"\d+", version_raw)]
    if not parts:
        return False
    normalized = parts[: len(minimum)]
    if len(normalized) < len(minimum):
        normalized.extend([0] * (len(minimum) - len(normalized)))
    return tuple(normalized) >= minimum


async def _run_webhook_server(settings: Settings) -> None:
    """Start the TradingView webhook server using uvicorn on the current loop."""

    host, port = _resolve_webhook_binding()
    if not settings.tls_cert_path or not settings.tls_key_path:
        raise RuntimeError(
            "TLS certificate and key must be configured when the webhook is enabled."
        )

    app = create_app(settings=settings)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_certfile=str(settings.tls_cert_path),
        ssl_keyfile=str(settings.tls_key_path),
        loop="asyncio",
        log_level="info",
    )
    server = uvicorn.Server(config)

    supports_modern_lifespan = (
        hasattr(server, "main_loop")
        and hasattr(server, "lifespan")
        and _is_uvicorn_compatible(uvicorn.__version__, UVICORN_MIN_VERSION)
    )

    if not supports_modern_lifespan and not hasattr(server, "serve"):
        raise RuntimeError(
            "The installed uvicorn version is too old to run the TradingView webhook server."
        )

    if not supports_modern_lifespan:
        LOGGER.warning(
            "Running TradingView webhook server with legacy uvicorn %s. "
            "Upgrade to uvicorn>=0.20 for improved lifespan management.",
            getattr(uvicorn, "__version__", "unknown"),
        )

    server.install_signal_handlers = False

    LOGGER.info(
        "Starting TradingView webhook server at https://%s:%s/tradingview-webhook",
        host,
        port,
    )

    try:
        if supports_modern_lifespan:
            try:
                await server.startup()
            except AttributeError as exc:
                LOGGER.warning(
                    "Falling back to uvicorn Server.serve() due to missing lifespan support: %s",
                    exc,
                )
                supports_modern_lifespan = False
            except Exception:  # pragma: no cover - startup errors are surfaced to the CLI
                LOGGER.exception("Failed to start TradingView webhook server")
                raise

        if supports_modern_lifespan and not server.started.is_set():  # pragma: no cover - defensive guard
            raise RuntimeError("TradingView webhook server failed to start")

        if supports_modern_lifespan:
            try:
                await server.main_loop()
            except asyncio.CancelledError:
                LOGGER.info("Stopping TradingView webhook server")
                server.should_exit = True
                raise
        else:
            serve_result = server.serve()
            if not inspect.isawaitable(serve_result):  # pragma: no cover - unsupported uvicorn build
                raise RuntimeError(
                    "The installed uvicorn version does not provide an awaitable Server.serve()."
                )

            serve_task = asyncio.create_task(serve_result)
            started_event = getattr(server, "started", None)

            try:
                if isinstance(started_event, asyncio.Event):
                    await started_event.wait()
                    if serve_task.done():
                        await serve_task
                        if not server.should_exit:
                            raise RuntimeError("TradingView webhook server failed to start")

                await serve_task
            except asyncio.CancelledError:
                LOGGER.info("Stopping TradingView webhook server")
                server.should_exit = True
                serve_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await serve_task
                raise
    except asyncio.CancelledError:
        raise
    else:
        if not server.should_exit:
            raise RuntimeError("TradingView webhook server stopped unexpectedly")
    finally:
        with contextlib.suppress(Exception):
            shutdown_result = server.shutdown()
            if asyncio.iscoroutine(shutdown_result):
                await shutdown_result


async def _run_application(settings: Settings) -> None:
    """Run the Telegram bot and optional webhook server until shutdown."""

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _request_shutdown() -> None:
        if not shutdown_event.is_set():
            LOGGER.info("Shutdown signal received. Stopping services...")
            shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    tasks: list[asyncio.Task[None]] = []

    bot_task = loop.create_task(run_bot(settings), name="telegram-bot")
    tasks.append(bot_task)

    if settings.tradingview_webhook_enabled:
        webhook_task = loop.create_task(
            _run_webhook_server(settings), name="tradingview-webhook"
        )
        tasks.append(webhook_task)
    else:
        LOGGER.info("TradingView webhook disabled. Only starting Telegram bot.")

    def _propagate_exit(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            LOGGER.exception("Service task failed", exc_info=exc)
        if not shutdown_event.is_set():
            shutdown_event.set()

    for task in tasks:
        task.add_done_callback(_propagate_exit)

    await shutdown_event.wait()

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


def main() -> None:
    """CLI entry point that loads settings and starts all services."""

    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )

    try:
        settings = get_settings()
    except RuntimeError as error:
        LOGGER.error("Configuration error: %s", error)
        raise

    try:
        asyncio.run(_run_application(settings))
    except KeyboardInterrupt:  # pragma: no cover - manual interruption
        LOGGER.info("Interrupted by user. Exiting...")


if __name__ == "__main__":
    main()
