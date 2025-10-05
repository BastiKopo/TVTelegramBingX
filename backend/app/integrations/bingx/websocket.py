"""BingX WebSocket helpers."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import websockets


BingXWebSocketHandler = Callable[[dict[str, Any]], Awaitable[None]]


class BingXWebSocketSubscriber:
    """Manage BingX private WebSocket subscriptions for orders and positions."""

    def __init__(
        self,
        url: str,
        api_key: str,
        signature_factory: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        heartbeat_interval: float = 15.0,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._signature_factory = signature_factory
        self._heartbeat_interval = heartbeat_interval
        self._tasks: set[asyncio.Task] = set()
        self._stop_event = asyncio.Event()

    async def run(self, channels: list[str], handler: BingXWebSocketHandler) -> None:
        """Subscribe to the given ``channels`` and pass payloads to ``handler``."""

        auth_payload = self._signature_factory({"apiKey": self._api_key})
        subscribe_message = json.dumps({"op": "subscribe", "args": channels, **auth_payload})
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self._url, ping_interval=None) as connection:
                    await connection.send(subscribe_message)
                    heartbeat_task = asyncio.create_task(self._heartbeat(connection))
                    async for raw in connection:
                        data = json.loads(raw)
                        await handler(data)
                    heartbeat_task.cancel()
            except (OSError, websockets.WebSocketException):
                await asyncio.sleep(2)

    async def _heartbeat(self, connection: websockets.WebSocketClientProtocol) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await connection.ping()
            except websockets.WebSocketException:
                return

    async def close(self) -> None:
        self._stop_event.set()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


__all__ = ["BingXWebSocketSubscriber", "BingXWebSocketHandler"]
