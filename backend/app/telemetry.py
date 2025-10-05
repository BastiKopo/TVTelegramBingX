"""Telemetry helpers for the FastAPI backend."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_INITIALISED = False


def _build_exporter_kwargs(settings: Settings) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if settings.telemetry_otlp_endpoint:
        kwargs["endpoint"] = settings.telemetry_otlp_endpoint
    if settings.telemetry_otlp_headers:
        kwargs["headers"] = settings.telemetry_otlp_headers
    return kwargs


def _queue_depth_observer(app: FastAPI):  # type: ignore[override]
    try:
        from opentelemetry.metrics import Observation
    except Exception:  # pragma: no cover - otel not installed
        return []

    queue = getattr(app.state, "signal_queue", None)
    if queue is None:
        return []

    try:
        size = queue.qsize()
    except Exception:  # pragma: no cover - platform specific
        size = 0
    return [Observation(size, {"queue": "signals"})]


def configure_backend_telemetry(app: FastAPI, *, settings: Settings | None = None) -> None:
    """Initialise OpenTelemetry providers and instrumentation."""

    global _INITIALISED
    if _INITIALISED:
        return

    settings = settings or get_settings()
    if not settings.telemetry_enabled:
        logger.info("Telemetry disabled via configuration")
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception:  # pragma: no cover - otel missing
        logger.warning("OpenTelemetry packages missing; backend telemetry disabled")
        return

    exporter_kwargs = _build_exporter_kwargs(settings)
    resource = Resource(attributes={
        "service.name": settings.telemetry_service_name,
        "service.namespace": "tvtelegrambingx",
        "deployment.environment": settings.environment,
    })

    tracer_provider = TracerProvider(
        resource=resource, sampler=TraceIdRatioBased(settings.telemetry_sample_ratio)
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter(**exporter_kwargs)
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(metric_exporter)],
    )
    metrics.set_meter_provider(meter_provider)

    meter = metrics.get_meter("tvtelegrambingx.backend")
    meter.create_observable_gauge(
        "tvtelegrambingx_signal_queue_depth",
        description="Number of TradingView signals waiting for execution",
        callbacks=[lambda: _queue_depth_observer(app)],
    )

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    try:
        AsyncPGInstrumentor().instrument()
    except Exception:  # pragma: no cover - driver not available
        logger.debug("AsyncPG instrumentation not available", exc_info=True)
    try:
        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception:  # pragma: no cover - optional feature
        logger.debug("Logging instrumentation not available", exc_info=True)

    _INITIALISED = True

*** End of File
