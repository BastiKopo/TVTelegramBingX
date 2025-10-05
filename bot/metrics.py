"""Prometheus metrics helpers for the Telegram bot."""
from __future__ import annotations

try:  # pragma: no cover - optional dependency
    from prometheus_client import Counter, Histogram, start_http_server
except Exception:  # pragma: no cover - dependency missing
    Counter = Histogram = None  # type: ignore

    def start_http_server(*_args, **_kwargs):  # type: ignore
        raise RuntimeError("prometheus-client is required for bot metrics")

_backend_request_counter = None
_backend_request_latency = None
_bot_update_counter = None


if Counter is not None:  # pragma: no branch - initialise when available
    _backend_request_counter = Counter(
        "tvtelegrambingx_bot_backend_requests_total",
        "HTTP requests issued by the bot towards the backend",
        labelnames=("method", "path", "status"),
    )
    _bot_update_counter = Counter(
        "tvtelegrambingx_bot_updates_total",
        "Telegram updates processed by the bot",
        labelnames=("type",),
    )

if Histogram is not None:  # pragma: no branch - initialise when available
    _backend_request_latency = Histogram(
        "tvtelegrambingx_bot_backend_request_duration_seconds",
        "Latency of bot to backend HTTP requests",
        labelnames=("method", "path"),
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
    )


def observe_backend_request(method: str, path: str, status: int, duration: float) -> None:
    """Record metrics for backend HTTP calls."""

    if _backend_request_latency is not None:
        _backend_request_latency.labels(method=method, path=path).observe(duration)
    if _backend_request_counter is not None:
        _backend_request_counter.labels(method=method, path=path, status=str(status)).inc()


def increment_update(update_type: str) -> None:
    """Increment the counter for processed Telegram updates."""

    if _bot_update_counter is not None:
        _bot_update_counter.labels(type=update_type).inc()


def start_metrics_server(host: str, port: int) -> None:
    """Start the HTTP endpoint that exposes Prometheus metrics."""

    try:
        start_http_server(port, addr=host)
    except RuntimeError as exc:  # pragma: no cover - dependency missing
        if "prometheus-client" in str(exc):
            raise
        # Re-raise any other runtime error
        raise


__all__ = [
    "observe_backend_request",
    "increment_update",
    "start_metrics_server",
]
