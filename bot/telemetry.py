"""Telemetry bootstrap for the Telegram bot."""
from __future__ import annotations

import logging

from .config import BotSettings

logger = logging.getLogger(__name__)

_INITIALISED = False


def _build_exporter_kwargs(settings: BotSettings) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if settings.telemetry_otlp_endpoint:
        kwargs["endpoint"] = settings.telemetry_otlp_endpoint
    if settings.telemetry_otlp_headers:
        kwargs["headers"] = settings.telemetry_otlp_headers
    return kwargs


def configure_bot_telemetry(settings: BotSettings) -> None:
    """Initialise OpenTelemetry exporters and HTTPX instrumentation."""

    global _INITIALISED
    if _INITIALISED:
        return
    if not settings.telemetry_enabled:
        logger.info("Bot telemetry disabled via configuration")
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception:  # pragma: no cover - otel missing
        logger.warning("OpenTelemetry packages missing; bot telemetry disabled")
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

    HTTPXClientInstrumentor().instrument()
    try:
        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception:  # pragma: no cover - optional instrumentation
        logger.debug("Failed to enable logging instrumentation", exc_info=True)

    _INITIALISED = True
*** End of File
