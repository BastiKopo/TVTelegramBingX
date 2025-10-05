"""Domain service handling TradingView signal ingestion."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ..repositories.signal_repository import SignalRepository
from ..schemas import Signal, TradingViewSignal


class SignalPublisher(Protocol):
    """Protocol describing queue publishers used for downstream processing."""

    async def publish(self, channel: str, payload: dict) -> None:
        """Publish a payload to the given channel."""


@dataclass(slots=True)
class InMemoryPublisher:
    """Lightweight in-memory publisher for development and tests."""

    queue: asyncio.Queue

    async def publish(self, channel: str, payload: dict) -> None:  # noqa: D401
        await self.queue.put((channel, payload))


class SignalService:
    """Coordinates validation, persistence and queue publishing of signals."""

    def __init__(self, repository: SignalRepository, publisher: SignalPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    async def ingest(self, payload: TradingViewSignal) -> Signal:
        signal = Signal(
            symbol=payload.symbol,
            action=payload.action,
            confidence=payload.confidence,
            timestamp=payload.timestamp,
            quantity=payload.quantity,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            leverage=payload.leverage,
            margin_mode=payload.margin_mode,
            raw_payload=payload.model_dump(),
        )
        stored = await self._repository.create(signal)
        await self._publisher.publish("signals.validated", stored.raw_payload)
        return stored

    async def list_recent(self, limit: int = 50) -> list[Signal]:
        return list(await self._repository.list_recent(limit))
