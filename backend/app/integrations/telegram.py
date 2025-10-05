"""Telegram notification utilities."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

import httpx


class SignalNotifier(Protocol):
    """Protocol describing services able to notify about processed signals."""

    async def notify(self, message: str) -> None:
        """Send a human-readable notification."""


class TelegramNotifier:
    """Notifier that relays signal updates to a Telegram chat via the Bot API."""

    def __init__(self, token: str, chat_id: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._chat_id = chat_id
        if client is None:
            self._client = httpx.AsyncClient()
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    async def notify(self, message: str) -> None:  # noqa: D401
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        response = await self._client.post(
            url,
            json={
                "chat_id": self._chat_id,
                "text": message,
            },
            timeout=10.0,
        )
        response.raise_for_status()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


@dataclass(slots=True)
class InMemorySignalNotifier:
    """Simple notifier that stores messages in memory (e.g. for tests)."""

    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)

    async def notify(self, message: str) -> None:  # noqa: D401
        await self.queue.put(message)


__all__ = [
    "SignalNotifier",
    "TelegramNotifier",
    "InMemorySignalNotifier",
]
