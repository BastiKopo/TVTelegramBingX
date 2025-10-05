# Observability Guide

This project uses OpenTelemetry to capture metrics, traces, and structured logs from both the FastAPI backend and the Telegram bot. Instrumentation is disabled by default and can be toggled via environment variables shared across services.

## Enabling Telemetry

Set the following variables in the deployment environment (for both backend and bot processes):

```bash
export TELEMETRY_ENABLED=true
export TELEMETRY_SERVICE_NAME=tvtelegrambingx-backend  # or tvtelegrambingx-bot
export TELEMETRY_OTLP_ENDPOINT="http://otel-collector:4318"
export TELEMETRY_OTLP_HEADERS='{"Authorization": "Bearer <token>"}'
export TELEMETRY_SAMPLE_RATIO=0.2
export ENVIRONMENT=production
```

When enabled the backend automatically instruments FastAPI, asyncpg, and outbound HTTPX calls. The bot instruments HTTPX calls to the backend. Logging instrumentation adds trace and span identifiers to log messages.

## Metrics

Key emitted metrics include:

| Metric | Type | Description |
| ------ | ---- | ----------- |
| `tradingview_signals_ingested_total` | Counter | Count of TradingView signals persisted and queued. |
| `tradingview_signal_ingest_duration_seconds` | Histogram | Time to validate, persist, and publish TradingView signals. |
| `tvtelegrambingx_signal_queue_depth` | Observable Gauge | Current backlog of TradingView signals awaiting execution. |
| `trading_orders_submitted_total` | Counter | Successful submissions to BingX. |
| `trading_orders_failed_total` | Counter | Submissions that failed after retries. |
| `trading_order_submission_duration_seconds` | Histogram | Time to submit and persist exchange orders. |
| `bot_backend_requests_total` | Counter | HTTP requests emitted by the Telegram bot. |
| `bot_backend_request_duration_seconds` | Histogram | Latency for bot-to-backend traffic. |

## Tracing

Spans are emitted for signal ingestion (`SignalService.ingest`), order execution (`OrderService.handle_signal`), and bot HTTP interactions (`BackendClient`). Span attributes capture symbol, action, order identifiers, and HTTP status codes to aid troubleshooting. Export spans to an OTLP-compatible backend such as Tempo or Jaeger.

## Logs

Logging instrumentation enriches log records with `trace_id` and `span_id`. Forward application logs to Loki or your preferred log store to correlate events with traces. Ensure log level `INFO` is enabled in production to capture audit events from the bot and backend services.

## Collector and Alerting

Use the provided [OpenTelemetry Collector configuration](../monitoring/otel-collector.yaml) to forward metrics to Prometheus, traces to Tempo, and logs to Loki. Apply the sample [Prometheus alerting rules](../monitoring/alerting-rules.yaml) to trigger alerts on signal backlog, BingX failures, and bot connectivity issues.

### Example Grafana Dashboards

Build dashboards that visualise:

- Signal ingestion throughput and latency (`tradingview_signals_ingested_total`, latency histogram quantiles).
- Order submission success rates versus failures.
- Bot HTTP request success/failure rates.
- Queue depth over time to spot automation pauses.

Combine metrics with traces to quickly identify the failing component in the TradingView → Telegram → BingX flow.

## Alert Routing

Integrate alerts with PagerDuty, Opsgenie, or Slack. Recommended routing:

- `TradingViewSignalBacklog` → On-call trading automation engineer.
- `BingXOrderFailures` → Exchange integration team.
- `BotBackendReachability` → Platform on-call.

Configure escalation policies so unresolved alerts auto-escalate within 30 minutes.
