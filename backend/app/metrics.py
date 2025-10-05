"""Prometheus metrics helpers for the FastAPI backend."""
from __future__ import annotations
from collections import defaultdict
from typing import Callable

try:  # pragma: no cover - optional dependency
    from prometheus_client import Counter, Gauge, Histogram
except Exception:  # pragma: no cover - dependency missing
    Counter = Gauge = Histogram = None  # type: ignore


_signal_ingest_counter = None
_signal_ingest_latency = None
_order_status_counter = None
_order_value_counter = None
_realised_pnl_gauge = None
_total_realised_pnl_gauge = None
_signal_queue_gauge = None

# Keep track of running realised PnL per symbol so Gauge reflects totals.
_realised_pnl_totals: dict[str, float] = defaultdict(float)


if Counter is not None:  # pragma: no branch - initialise metrics when available
    _signal_ingest_counter = Counter(
        "tradingview_signals_ingested_total",
        "Number of TradingView signals processed by the backend",
        labelnames=("symbol", "action"),
    )

if Histogram is not None:  # pragma: no branch - initialise when available
    _signal_ingest_latency = Histogram(
        "tradingview_signal_ingest_duration_seconds",
        "Time taken to persist and enqueue TradingView signals",
        labelnames=("symbol",),
        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    )

if Counter is not None:  # pragma: no branch
    _order_status_counter = Counter(
        "tvtelegrambingx_order_transitions_total",
        "Order status transitions recorded by the backend",
        labelnames=("symbol", "status"),
    )

if Counter is not None:  # pragma: no branch
    _order_value_counter = Counter(
        "tvtelegrambingx_order_notional_usd_total",
        "Notional value of filled orders grouped by action",
        labelnames=("symbol", "action"),
    )

if Gauge is not None:  # pragma: no branch
    _realised_pnl_gauge = Gauge(
        "tvtelegrambingx_realised_pnl_usd",
        "Realised PnL aggregated per symbol",
        labelnames=("symbol",),
    )
    _total_realised_pnl_gauge = Gauge(
        "tvtelegrambingx_realised_pnl_total_usd",
        "Realised PnL aggregated across all symbols",
    )
    _signal_queue_gauge = Gauge(
        "tvtelegrambingx_signal_queue_depth",
        "Depth of the in-memory TradingView signal queue",
        labelnames=("queue",),
    )


def observe_signal_ingest(symbol: str, action: str, duration: float) -> None:
    """Record metrics for TradingView signal ingestion."""

    if _signal_ingest_counter is not None:
        _signal_ingest_counter.labels(symbol=symbol, action=action).inc()
    if _signal_ingest_latency is not None:
        _signal_ingest_latency.labels(symbol=symbol).observe(duration)


def record_order_status(symbol: str, status: str) -> None:
    """Increment the order status counter."""

    if _order_status_counter is not None:
        _order_status_counter.labels(symbol=symbol, status=status).inc()


def record_order_fill(symbol: str, action: str, price: float | None, quantity: float | None) -> None:
    """Record metrics when an order is filled."""

    if price is None or quantity is None:
        return

    notional = price * quantity
    if _order_value_counter is not None:
        _order_value_counter.labels(symbol=symbol, action=action).inc(notional)

    if _realised_pnl_gauge is None or _total_realised_pnl_gauge is None:
        return

    if action.lower() == "sell":
        delta = notional
    else:
        delta = -notional
    _realised_pnl_totals[symbol] += delta
    _realised_pnl_gauge.labels(symbol=symbol).set(_realised_pnl_totals[symbol])
    _total_realised_pnl_gauge.set(sum(_realised_pnl_totals.values()))


def bind_signal_queue_depth(size_fn: Callable[[], int]) -> None:
    """Expose a callable that returns the queue depth when scraped."""

    if _signal_queue_gauge is None:
        return
    _signal_queue_gauge.labels(queue="signals").set_function(lambda: float(size_fn()))


__all__ = [
    "observe_signal_ingest",
    "record_order_status",
    "record_order_fill",
    "bind_signal_queue_depth",
]
