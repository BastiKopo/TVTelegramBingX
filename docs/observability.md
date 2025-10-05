# Observability Guide

This project uses OpenTelemetry to capture metrics, traces, and structured logs from both the FastAPI backend and the Telegram bot. Instrumentation is disabled by default and can be toggled via environment variables shared across services. Native Prometheus exporters are available for teams that prefer direct scraping without an OpenTelemetry Collector.

## Prometheus & Grafana deployment prerequisites

Choose the deployment model that aligns with your existing infrastructure footprint:

### Native packages on Ubuntu/Debian hosts

1. **Prometheus** – install the official package repository and configure storage:

   ```bash
   sudo useradd --no-create-home --shell /usr/sbin/nologin prometheus
   sudo mkdir -p /etc/prometheus /var/lib/prometheus
   sudo apt update && sudo apt install -y prometheus prometheus-node-exporter
   ```

   The Debian package creates a systemd service. Replace `/etc/prometheus/prometheus.yml` with the provided [scrape configuration](../monitoring/prometheus.yaml) and restart the service (`sudo systemctl restart prometheus`). Ensure the firewall allows inbound traffic from your Grafana or Alertmanager hosts.

2. **Grafana** – install from the official repository to receive timely updates:

   ```bash
   sudo apt install -y apt-transport-https software-properties-common
   wget -q -O - https://packages.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
   echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://packages.grafana.com/oss/deb stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
   sudo apt update && sudo apt install -y grafana
   sudo systemctl enable --now grafana-server
   ```

   Add the Prometheus URL (for example `http://prometheus.internal:9090`) as a datasource within Grafana.

### Managed services

* **Prometheus-compatible backends** – AWS Managed Service for Prometheus, Google Managed Service for Prometheus, Grafana Cloud, or VictoriaMetrics Cloud. Provision a workspace/instance and obtain the remote write endpoint plus an API token. When using AWS or GCP managed services, deploy an in-region Prometheus agent (AMP Collector / Managed Prometheus Agent) configured with the sample scrape jobs.
* **Grafana Cloud or Managed Grafana** – create an organisation, generate API keys for provisioning dashboards, and connect the managed Prometheus datasource. Assign SSO groups/roles in line with your existing IAM provider.

For both models ensure network access (VPC peering or VPN) from the monitoring stack to the backend (`:8000/metrics`) and bot exporter (`:9000/metrics`) hosts, and register DNS entries that reflect your service naming conventions.

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
| `tradingview_signals_ingested_total` | Counter | Count of TradingView signals persisted and queued (mirrored in Prometheus). |
| `tradingview_signal_ingest_duration_seconds` | Histogram | Time to validate, persist, and publish TradingView signals (mirrored in Prometheus). |
| `tvtelegrambingx_signal_queue_depth` | Observable Gauge / Gauge | Current backlog of TradingView signals awaiting execution. |
| `tvtelegrambingx_order_transitions_total` | Counter | Order lifecycle transitions grouped by symbol and status. |
| `tvtelegrambingx_order_notional_usd_total` | Counter | Aggregated notional value (USD) of filled orders by action. |
| `tvtelegrambingx_realised_pnl_usd` | Gauge | Realised PnL per symbol calculated from filled buy/sell orders. |
| `tvtelegrambingx_realised_pnl_total_usd` | Gauge | Realised PnL aggregated across all symbols. |
| `tvtelegrambingx_bot_backend_requests_total` | Counter | HTTP requests emitted by the Telegram bot. |
| `tvtelegrambingx_bot_backend_request_duration_seconds` | Histogram | Latency for bot-to-backend traffic. |
| `tvtelegrambingx_bot_updates_total` | Counter | Processed Telegram messages and callback queries. |

### Prometheus scraping

Both services now expose native `/metrics` endpoints. Configure scrape jobs using the sample [Prometheus configuration](../monitoring/prometheus.yaml):

```yaml
scrape_configs:
  - job_name: tvtelegrambingx-backend
    metrics_path: /metrics
    static_configs:
      - targets: ["backend.internal:8000"]
  - job_name: tvtelegrambingx-bot
    static_configs:
      - targets: ["bot.internal:9000"]
```

Set `BOT_METRICS_ENABLED=true` (default) to start the bot exporter. If the `prometheus-client` package is missing, the bot logs a warning and continues without exposing metrics. For hardened environments place the exporters behind an internal load balancer or reverse proxy that enforces mTLS.

### Grafana dashboards

Import the [TVTelegramBingX Overview](../monitoring/grafana/tvtelegrambingx-overview.json) dashboard to visualise signal throughput, order success rates, realised PnL, queue depth, and bot request latencies out of the box. Clone the dashboard per environment and adjust templated variables (symbols, environments) as required.

## Tracing

Spans are emitted for signal ingestion (`SignalService.ingest`), order execution (`OrderService.handle_signal`), and bot HTTP interactions (`BackendClient`). Span attributes capture symbol, action, order identifiers, and HTTP status codes to aid troubleshooting. Export spans to an OTLP-compatible backend such as Tempo or Jaeger.

## Logs

Logging instrumentation enriches log records with `trace_id` and `span_id`. Forward application logs to Loki or your preferred log store to correlate events with traces. Ensure log level `INFO` is enabled in production to capture audit events from the bot and backend services.

## Collector and Alerting

Use the provided [OpenTelemetry Collector configuration](../monitoring/otel-collector.yaml) to forward metrics to Prometheus, traces to Tempo, and logs to Loki when you prefer the collector pattern. Apply the sample [Prometheus alerting rules](../monitoring/alerting-rules.yaml) to trigger alerts on signal backlog, BingX failures, and bot connectivity issues.

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
