"""Domain service handling TradingView signal ingestion."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ..config import Settings
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

    def __init__(self, repository: SignalRepository, publisher: SignalPublisher, settings: Settings) -> None:
        self._repository = repository
        self._publisher = publisher
        self._settings = settings

    async def ingest(self, payload: TradingViewSignal) -> Signal:
        effective_leverage = (
            payload.leverage if payload.leverage is not None else self._settings.default_leverage
        )
        effective_margin_mode = (
            payload.margin_mode
            if payload.margin_mode is not None
            else self._settings.default_margin_mode
        )
        raw_payload = payload.model_dump()
        if raw_payload.get("leverage") is None:
            raw_payload["leverage"] = effective_leverage
        if raw_payload.get("margin_mode") is None:
            raw_payload["margin_mode"] = effective_margin_mode
        signal = Signal(
            symbol=payload.symbol,
            action=payload.action,
            confidence=payload.confidence,
            timestamp=payload.timestamp,
            quantity=payload.quantity,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            leverage=effective_leverage,
            margin_mode=effective_margin_mode,
            raw_payload=raw_payload,
        )
        stored = await self._repository.create(signal)
        await self._publisher.publish("signals.validated", stored.raw_payload)
        return stored

    async def list_recent(self, limit: int = 50) -> list[Signal]:
        return list(await self._repository.list_recent(limit))
