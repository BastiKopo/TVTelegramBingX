"""Tests for the CLI entry point helpers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from config import Settings

if "uvicorn" not in sys.modules:
    sys.modules["uvicorn"] = SimpleNamespace(Config=object, Server=object, __version__="0.0.0")

if "telegram" not in sys.modules:
    sys.modules["telegram"] = SimpleNamespace(Update=object)

if "telegram.ext" not in sys.modules:
    class _ContextTypes:
        DEFAULT_TYPE = object()

    sys.modules["telegram.ext"] = SimpleNamespace(
        Application=object,
        ApplicationBuilder=object,
        CommandHandler=object,
        ContextTypes=_ContextTypes,
    )

if "bot" not in sys.modules:
    sys.modules["bot"] = ModuleType("bot")

if "bot.telegram_bot" not in sys.modules:
    bot_module = ModuleType("bot.telegram_bot")

    async def _run_bot_stub(settings):  # pragma: no cover - helper for import-time stubbing
        await asyncio.sleep(0)

    bot_module.run_bot = _run_bot_stub
    sys.modules["bot.telegram_bot"] = bot_module
    sys.modules["bot"].telegram_bot = bot_module  # type: ignore[attr-defined]

if "webhook" not in sys.modules:
    sys.modules["webhook"] = ModuleType("webhook")

if "webhook.server" not in sys.modules:
    server_module = ModuleType("webhook.server")

    def _create_app_stub(*args, **kwargs):  # pragma: no cover - helper for import-time stubbing
        return object()

    server_module.create_app = _create_app_stub
    sys.modules["webhook.server"] = server_module
    sys.modules["webhook"].server = server_module  # type: ignore[attr-defined]

import tvtelegrambingx.main as main


def _make_settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        bingx_api_key="key",
        bingx_api_secret="secret",
        tradingview_webhook_enabled=True,
        tradingview_webhook_secret="webhook-secret",
        tls_cert_path=Path("cert.pem"),
        tls_key_path=Path("key.pem"),
    )


def test_run_webhook_server_supports_legacy_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Older uvicorn builds without ``main_loop`` should still run the server."""

    settings = _make_settings()

    created_servers: list[DummyServer] = []

    class DummyConfig:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class DummyServer:
        def __init__(self, config: DummyConfig):
            self.config = config
            self.install_signal_handlers = True
            self.should_exit = False
            self.shutdown_called = False
            self.started = asyncio.Event()
            created_servers.append(self)

        async def serve(self):
            self.started.set()
            try:
                while not self.should_exit:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                raise

        async def shutdown(self):
            self.shutdown_called = True

    dummy_uvicorn = SimpleNamespace(
        Config=DummyConfig,
        Server=DummyServer,
        __version__="0.18.0",
    )

    monkeypatch.setattr(main, "uvicorn", dummy_uvicorn)
    monkeypatch.setattr(main, "create_app", lambda settings: object())

    async def _run_and_cancel() -> None:
        task = asyncio.create_task(main._run_webhook_server(settings))
        await asyncio.sleep(0.05)

        server = created_servers[-1]
        assert server.install_signal_handlers is False

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert server.shutdown_called is True

    asyncio.run(_run_and_cancel())
