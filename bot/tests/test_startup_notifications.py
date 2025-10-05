"""Tests for startup notification broadcasting."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ..main import _announce_startup, TelegramForbiddenError
from ..models import BotState


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_startup_notification_sent_to_all_recipients(caplog: pytest.LogCaptureFixture) -> None:
    bot = AsyncMock()
    client = AsyncMock()
    client.get_state.return_value = BotState(
        auto_trade_enabled=True,
        manual_confirmation_required=False,
        margin_mode="cross",
        leverage=10,
    )
    settings = SimpleNamespace(admin_ids={1, 2}, broadcast_chat_id=3)

    caplog.set_level(logging.INFO)

    await _announce_startup(bot, client, settings)

    assert client.get_state.await_count == 1
    assert bot.send_message.await_count == 3
    sent_to = {call.args[0] for call in bot.send_message.await_args_list}
    assert sent_to == {1, 2, 3}


@pytest.mark.anyio
async def test_startup_notification_logs_forbidden_error(caplog: pytest.LogCaptureFixture) -> None:
    bot = AsyncMock()
    client = AsyncMock()
    client.get_state.return_value = BotState()

    async def _send_message(chat_id: int, _: str) -> None:
        if chat_id == 2:
            raise TelegramForbiddenError("Forbidden")

    bot.send_message.side_effect = _send_message

    settings = SimpleNamespace(admin_ids={1, 2}, broadcast_chat_id=None)

    with caplog.at_level(logging.WARNING):
        await _announce_startup(bot, client, settings)

    assert bot.send_message.await_count == 2
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings, "Expected a warning log entry"
    assert warnings[0].message.startswith("Startup notification forbidden")
