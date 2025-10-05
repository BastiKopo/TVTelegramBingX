"""Utilities for dispatching webhook alerts to the Telegram bot."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

AlertPayload = Mapping[str, Any]

_ALERT_QUEUE: asyncio.Queue[AlertPayload] = asyncio.Queue()


def get_alert_queue() -> asyncio.Queue[AlertPayload]:
    """Return the shared asyncio queue for TradingView alerts."""

    return _ALERT_QUEUE


async def publish_alert(alert: AlertPayload) -> None:
    """Add a validated alert to the shared queue."""

    await _ALERT_QUEUE.put(alert)


__all__ = ["AlertPayload", "get_alert_queue", "publish_alert"]
