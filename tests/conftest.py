"""Pytest configuration for the TVTelegramBingX test suite."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


if "telegram" not in sys.modules:
    class _StubInlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, **kwargs) -> None:
            self.text = text
            self.callback_data = callback_data
            self.kwargs = kwargs

    class _StubInlineKeyboardMarkup:
        def __init__(self, inline_keyboard) -> None:
            self.inline_keyboard = inline_keyboard

    class _StubReplyKeyboardMarkup:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubBotCommand:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubUpdate:
        message = None

    sys.modules["telegram"] = SimpleNamespace(
        BotCommand=_StubBotCommand,
        InlineKeyboardButton=_StubInlineKeyboardButton,
        InlineKeyboardMarkup=_StubInlineKeyboardMarkup,
        ReplyKeyboardMarkup=_StubReplyKeyboardMarkup,
        Update=_StubUpdate,
    )


if "telegram.ext" not in sys.modules:
    class _StubCallbackQueryHandler:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubApplication:
        def __init__(self) -> None:
            self.bot_data: dict[str, object] = {}
            self.bot = SimpleNamespace(
                set_my_commands=lambda *args, **kwargs: None,
                send_message=lambda *args, **kwargs: None,
            )

        def add_handler(self, handler) -> None:
            self.bot_data.setdefault("handlers", []).append(handler)

    class _StubApplicationBuilder:
        def __init__(self) -> None:
            self._token = None

        def token(self, value: str) -> "_StubApplicationBuilder":
            self._token = value
            return self

        def build(self) -> _StubApplication:
            return _StubApplication()

    class _StubCommandHandler:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _StubContextTypes:
        DEFAULT_TYPE = object()

    sys.modules["telegram.ext"] = SimpleNamespace(
        Application=_StubApplication,
        ApplicationBuilder=_StubApplicationBuilder,
        CallbackQueryHandler=_StubCallbackQueryHandler,
        CommandHandler=_StubCommandHandler,
        ContextTypes=_StubContextTypes,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_fastapi_shim() -> None:
    if "fastapi" in sys.modules:
        return

    module_path = PROJECT_ROOT / "fastapi" / "__init__.py"
    if not module_path.exists():
        return

    spec = importlib.util.spec_from_file_location("fastapi", module_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules["fastapi"] = module
        spec.loader.exec_module(module)


import importlib
import importlib.util  # noqa: E402  - used by the shim loader

_load_fastapi_shim()


def _load_webhook_server() -> None:
    if "webhook.server" in sys.modules:
        return

    importlib.import_module("webhook.server")


_load_webhook_server()
