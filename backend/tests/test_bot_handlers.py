from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.config import BotSettings
from bot.handlers import BotHandlers
from bot.middleware import AdminMiddleware
from bot.models import BalanceSnapshot, BotState, OpenPositionSnapshot, PnLSummary


class DummyBackendClient:
    def __init__(self) -> None:
        self.state = BotState()
        self.updated_payload: dict[str, object] | None = None

    async def get_state(self) -> BotState:
        return self.state

    async def update_state(self, **kwargs) -> BotState:
        self.updated_payload = kwargs
        for key, value in kwargs.items():
            setattr(self.state, key, value)
        return self.state

    async def fetch_recent_signals(self, limit: int):
        return []


class DummyMessage:
    def __init__(self, text: str = "", user_id: int = 1, username: str = "admin") -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.replies: list[dict] = []

    async def answer(self, text: str, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})
        return SimpleNamespace()


class DummyEditableMessage(DummyMessage):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.edits: list[dict] = []

    async def edit_text(self, text: str, **kwargs):
        self.edits.append({"text": text, "kwargs": kwargs})
        return SimpleNamespace()


class DummyCallbackQuery:
    def __init__(self, data: str, user_id: int = 1, username: str = "admin") -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.message = DummyEditableMessage()
        self.answers: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs):
        self.answers.append({"text": text, "kwargs": kwargs})
        return True


@pytest.mark.asyncio
async def test_toggle_autotrade_command_updates_state():
    settings = BotSettings(
        telegram_bot_token="token",
        telegram_admin_ids="1",
        backend_base_url="http://test",
    )
    client = DummyBackendClient()
    handlers = BotHandlers(client, settings)
    message = DummyMessage(text="/autotrade")

    await handlers.toggle_autotrade(message)

    assert client.updated_payload == {"auto_trade_enabled": True}
    assert any("Auto-Trade: ON" in reply["text"] for reply in message.replies)


@pytest.mark.asyncio
async def test_leverage_callback_updates_keyboard():
    settings = BotSettings(
        telegram_bot_token="token",
        telegram_admin_ids="1",
        backend_base_url="http://test",
    )
    client = DummyBackendClient()
    handlers = BotHandlers(client, settings)
    callback = DummyCallbackQuery("leverage:10")

    await handlers.leverage_callback(callback)

    assert client.updated_payload == {"leverage": 10}
    assert any("x10" in edit["text"] for edit in callback.message.edits)
    assert callback.answers[0]["text"] == "Leverage set to x10"


@pytest.mark.asyncio
async def test_status_renders_metrics_block():
    settings = BotSettings(
        telegram_bot_token="token",
        telegram_admin_ids="1",
        backend_base_url="http://test",
    )
    client = DummyBackendClient()
    client.state = BotState(
        auto_trade_enabled=True,
        balances=[BalanceSnapshot(asset="USDT", free=100.0, locked=5.0, total=105.0)],
        pnl=PnLSummary(realized=12.5, unrealized=3.0, total=15.5),
        open_positions=[
            OpenPositionSnapshot(
                symbol="BTCUSDT",
                action="buy",
                quantity=0.1,
                entry_price=25000.0,
                leverage=5,
                opened_at=None,
            )
        ],
    )
    handlers = BotHandlers(client, settings)
    message = DummyMessage(text="/status")

    await handlers.status(message)

    assert message.replies, "Expected status response"
    text = message.replies[0]["text"]
    assert "<b>Balances</b>" in text
    assert "<b>PnL</b>" in text
    assert "<b>Open Positions</b>" in text


@pytest.mark.asyncio
async def test_admin_middleware_blocks_unauthorized_user():
    middleware = AdminMiddleware({1})
    unauthorized_message = DummyMessage(user_id=99)
    called = False

    async def handler(event, data):
        nonlocal called
        called = True

    await middleware(handler, unauthorized_message, {})

    assert not called
    assert unauthorized_message.replies
    assert "not authorized" in unauthorized_message.replies[0]["text"].lower()
