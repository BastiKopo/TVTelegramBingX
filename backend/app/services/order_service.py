"""Auto-trade orchestration leveraging BingX integrations."""
from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..integrations.bingx import BingXRESTClient, BingXRESTError
from ..repositories.order_repository import OrderRepository
from ..repositories.position_repository import PositionRepository
from ..schemas import OrderStatus, TradeAction


class CircuitBreakerOpen(RuntimeError):
    """Raised when the circuit breaker is open and operations are blocked."""


@dataclass(slots=True)
class CircuitBreaker:
    """Simple stateful circuit breaker implementation."""

    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    _failure_count: int = 0
    _opened_at: float | None = None

    def allow(self, now: float) -> bool:
        if self._opened_at is None:
            return True
        if now - self._opened_at >= self.recovery_timeout:
            self._failure_count = 0
            self._opened_at = None
            return True
        return False

    def record_success(self) -> None:
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self, now: float) -> None:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._opened_at = now


class OrderService:
    """Consume queue messages and submit BingX orders with resilience."""

    def __init__(
        self,
        order_repository: OrderRepository,
        position_repository: PositionRepository,
        client: BingXRESTClient,
        settings: Settings,
        queue: "asyncio.Queue[tuple[str, dict[str, Any]]]",
        *,
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.5,
    ) -> None:
        self._orders = order_repository
        self._positions = position_repository
        self._client = client
        self._settings = settings
        self._queue = queue
        self._breaker = circuit_breaker or CircuitBreaker()
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            channel, payload = await self._queue.get()
            if channel != self._settings.broker_validated_routing_key:
                continue
            await self.handle_signal(payload)

    async def handle_signal(self, payload: dict[str, Any]) -> None:
        now = asyncio.get_running_loop().time()
        if not self._breaker.allow(now):
            raise CircuitBreakerOpen("Order circuit breaker is open")

        order_id = payload.get("order_id")
        if not order_id:
            return
        order = await self._orders.get(order_id)
        if order is None:
            return

        symbol = payload.get("symbol", order.symbol)
        action = TradeAction(payload.get("action", order.action))
        margin_mode = payload.get("margin_mode", self._settings.default_margin_mode)
        leverage = int(payload.get("leverage", self._settings.default_leverage))
        quantity = float(payload.get("quantity", order.quantity))

        exchange_side = "BUY" if action == TradeAction.BUY else "SELL"
        request = {
            "symbol": symbol,
            "side": exchange_side,
            "type": payload.get("type", "MARKET"),
            "quantity": quantity,
        }

        attempt = 0
        while attempt < self._max_retries:
            try:
                await self._client.set_margin_mode(symbol, margin_mode)
                await self._client.set_leverage(symbol, leverage)
                response = await self._client.create_order(request)
                exchange_order_id = response.get("orderId") or response.get("order_id")
                price = float(response.get("avgPrice") or response.get("price") or 0.0)
                await self._orders.update_status(
                    order,
                    OrderStatus.SUBMITTED,
                    price=price if price > 0 else None,
                    exchange_order_id=exchange_order_id,
                )
                self._breaker.record_success()
                return
            except BingXRESTError:
                attempt += 1
                delay = self._compute_backoff(attempt)
                await asyncio.sleep(delay)
                continue
            except Exception:
                attempt += 1
                await asyncio.sleep(self._compute_backoff(attempt))
        self._breaker.record_failure(asyncio.get_running_loop().time())
        raise BingXRESTError("Unable to submit order to BingX after retries")

    def _compute_backoff(self, attempt: int) -> float:
        return min(30.0, (self._backoff_base ** attempt) + random.random())

    async def handle_order_update(self, data: dict[str, Any]) -> None:
        exchange_order_id = data.get("orderId") or data.get("order_id")
        if not exchange_order_id:
            return
        order = await self._orders.get_by_exchange_order_id(str(exchange_order_id))
        if order is None:
            return
        status_str = str(data.get("status", "")).lower()
        mapping = {
            "filled": OrderStatus.FILLED,
            "partial_fill": OrderStatus.SUBMITTED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        status = mapping.get(status_str, order.status)
        price = float(data.get("avgPrice") or data.get("price") or order.price or 0.0)
        await self._orders.update_status(order, status, price=price if price > 0 else None)

    async def handle_position_update(self, data: dict[str, Any]) -> None:
        symbol = data.get("symbol")
        if not symbol:
            return
        quantity = float(data.get("positionAmt", 0))
        if math.isclose(quantity, 0.0, abs_tol=1e-9):
            await self._positions.close_remote_position(symbol)
            return
        side = TradeAction.BUY if str(data.get("positionSide")).lower() in {"long", "buy"} else TradeAction.SELL
        entry_price = float(data.get("entryPrice", 0.0))
        leverage = int(data.get("leverage", 0))
        await self._positions.upsert_from_exchange(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            leverage=leverage,
        )

    async def stop(self) -> None:
        self._stop_event.set()


__all__ = ["OrderService", "CircuitBreaker", "CircuitBreakerOpen"]
