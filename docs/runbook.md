# Operations Runbook

This runbook covers daily tasks and diagnostic steps for the TradingView → Telegram → BingX automation.

## Daily Checks

1. **Service health** – Confirm `/health` returns `{"status": "ok"}`. Automate using a synthetic monitor.
2. **Queue depth** – Grafana panel for `tvtelegrambingx_signal_queue_depth` should remain near zero. Investigate spikes immediately.
3. **Recent alerts** – Review alert manager dashboard for unresolved incidents (`TradingViewSignalBacklog`, `BingXOrderFailures`, `BotBackendReachability`).
4. **Database health** – Check managed PostgreSQL metrics for connections, CPU, and storage growth.
5. **Telegram bot logs** – Verify the bot processed overnight commands without errors.

## Manual Signal Approval

If manual confirmations are enabled:

1. Use the Telegram bot `/status` command to view current state.
2. Approve or reject signals via the inline keyboard. Approved signals flow to the queue immediately.
3. Monitor the queue depth to ensure approvals clear the backlog.

## Draining the Automation

To pause automated trading:

1. Run `/autotrade` in Telegram to toggle auto trading OFF.
2. Confirm via `/status` that `Auto-Trade` reads `OFF`.
3. Allow existing queue items to finish processing. Monitor `tvtelegrambingx_signal_queue_depth` until it reaches zero.
4. Optionally set `manual_confirmation_required` to `true` to prevent new signals from executing without human approval.

## Deployments

Follow the [Deployment Guide](deployment_guide.md). After deployment:

- Run smoke tests: submit a synthetic TradingView webhook payload and confirm it reaches BingX via the stubbed execution job.
- Verify telemetry: ensure new spans appear in Tempo and metrics in Prometheus.
- Check Telegram bot connectivity by running `/status`.

## Common Issues

### Signal Backlog

- Check the BingX API status page for outages.
- Inspect circuit breaker state in logs (`CircuitBreakerOpen`).
- If manual confirmation is enabled, confirm an operator is online to approve orders.

### Bot Cannot Reach Backend

- Review alerts for `BotBackendReachability`.
- Confirm backend HTTPS certificate validity and DNS.
- Check load balancer security groups/firewall rules.

### Database Migration Failure

- Roll back to previous container build.
- Restore database snapshot if schema change partially applied.
- Run `alembic downgrade -1` when safe, then re-apply migrations after fix.

## Escalation

- First line: Platform on-call engineer.
- Second line: Trading automation owner.
- Third line: CTO for prolonged outages (>60 minutes).

Document incident follow-up in the shared postmortem repository within 72 hours.
