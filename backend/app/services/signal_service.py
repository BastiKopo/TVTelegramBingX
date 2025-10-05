"""Domain service handling TradingView signal ingestion."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

if TYPE_CHECKING:  # pragma: no cover
    import aio_pika

from ..config import Settings
from ..repositories.bot_session_repository import BotSessionRepository
from ..repositories.order_repository import OrderRepository
from ..repositories.signal_repository import SignalRepository
from ..repositories.user_repository import UserRepository
from ..schemas import Order, OrderStatus, Signal, TradingViewSignal


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


class BrokerPublisher:
    """Publish signals to the configured message broker."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        try:
            import aio_pika as _aio_pika
        except ModuleNotFoundError as exc:  # pragma: no cover - configuration error
            raise RuntimeError(
                "aio-pika must be installed to use the broker publisher"
            ) from exc

        self._aio_pika = _aio_pika
        self._connection = None
        self._channel = None
        self._exchange = None
        self._lock = asyncio.Lock()

    async def _ensure_exchange(self):  # -> aio_pika.abc.AbstractExchange
        if self._exchange is not None:
            return self._exchange

        async with self._lock:
            if self._exchange is not None:
                return self._exchange

            url = self._build_broker_url()
            self._connection = await self._aio_pika.connect_robust(url)
            self._channel = await self._connection.channel()
            self._exchange = await self._channel.declare_exchange(
                self._settings.broker_exchange,
                self._aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            return self._exchange

    def _build_broker_url(self) -> str:
        username = quote(self._settings.broker_username, safe="")
        password = quote(self._settings.broker_password, safe="")
        vhost = quote(self._settings.broker_virtual_host.lstrip("/"), safe="")
        host = self._settings.broker_host or "localhost"
        return f"amqp://{username}:{password}@{host}:{self._settings.broker_port}/{vhost}"

    async def publish(self, channel: str, payload: dict) -> None:  # noqa: D401
        exchange = await self._ensure_exchange()
        message = self._aio_pika.Message(
            body=json.dumps(payload, default=str).encode("utf-8"),
            content_type="application/json",
            delivery_mode=self._aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=channel)

    async def initialize(self) -> None:
        """Eagerly establish the broker connection."""

        await self._ensure_exchange()

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

        if self._connection is not None:
            await self._connection.close()
            self._connection = None

        self._exchange = None


class SignalService:
    """Coordinates validation, persistence and queue publishing of signals."""

    def __init__(
        self,
        repository: SignalRepository,
        order_repository: OrderRepository,
        user_repository: UserRepository,
        bot_session_repository: BotSessionRepository,
        publisher: SignalPublisher,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._order_repository = order_repository
        self._user_repository = user_repository
        self._bot_session_repository = bot_session_repository
        self._publisher = publisher
        self._settings = settings

    async def ingest(self, payload: TradingViewSignal) -> Signal:
        leverage = payload.leverage if payload.leverage is not None else self._settings.default_leverage
        margin_mode = (
            payload.margin_mode if payload.margin_mode is not None else self._settings.default_margin_mode
        )
        raw_payload = payload.model_dump()
        raw_payload["leverage"] = leverage
        raw_payload["margin_mode"] = margin_mode
        signal = Signal(
            symbol=payload.symbol,
            action=payload.action,
            confidence=payload.confidence,
            timestamp=payload.timestamp,
            quantity=payload.quantity,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            leverage=leverage,
            margin_mode=margin_mode,
            raw_payload=raw_payload,
        )
        stored = await self._repository.create(signal)
        user = await self._user_repository.get_or_create_by_username(
            self._settings.trading_default_username
        )
        bot_session = await self._bot_session_repository.get_or_create_active_session(
            user.id, self._settings.trading_default_session
        )
        order = Order(
            signal_id=stored.id,
            user_id=user.id,
            bot_session_id=bot_session.id,
            symbol=stored.symbol,
            action=stored.action,
            status=OrderStatus.PENDING,
            quantity=stored.quantity,
        )
        await self._order_repository.create(order)
        enrichment = {
            "signal_id": stored.id,
            "order_id": order.id,
            "user_id": user.id,
            "bot_session_id": bot_session.id,
        }
        raw_payload.update(enrichment)
        stored.raw_payload.update(enrichment)
        await self._publisher.publish(self._settings.broker_validated_routing_key, stored.raw_payload)
        return stored

    async def list_recent(self, limit: int = 50) -> list[Signal]:
        return list(await self._repository.list_recent(limit))
