# Incident Response Plan

This guide defines the procedure for responding to production incidents affecting the TV → Telegram → BingX automation.

## Severity Levels

- **SEV1 (Critical)** – Trading halted, funds at risk, or widespread customer impact.
- **SEV2 (High)** – Trading degraded (delays, retries) but partially functional.
- **SEV3 (Medium)** – Minor feature impact or single user affected.

## 1. Detection

Incidents can be raised via alerting rules, customer reports, or operator observation. The first responder must create an incident ticket with timestamp, services affected, and initial symptoms.

## 2. Containment

1. Disable auto trading via Telegram `/autotrade` or `/bot/settings` API.
2. If exchange integration compromised, revoke BingX API keys immediately.
3. For data integrity incidents, snapshot the database before applying fixes.

## 3. Investigation

- Review Grafana dashboards for metrics anomalies (queue depth, order failures).
- Inspect traces in Tempo for slow spans or error statuses.
- Search Loki logs for correlated errors (look for `trace_id`).
- Validate TradingView webhook signatures/token usage.

## 4. Remediation

- Restart affected services using `systemctl restart tvtelegrambingx-backend` and `tvtelegrambingx-bot`.
- Deploy hotfixes following the CI/CD pipeline once tests pass.
- Coordinate with BingX support if the issue is upstream.

## 5. Recovery

- Re-enable auto trading after confirming the queue is empty and new signals process correctly.
- Monitor alerts for at least 30 minutes before closing the incident.

## 6. Post-Incident

- Publish a summary in the #trading-ops Slack channel.
- Schedule a blameless postmortem within 72 hours. Include metrics, timeline, root cause, action items, and owners.
- Track action items in the engineering backlog with due dates.

## Communication Templates

**Customer Update:**

> We are investigating an issue affecting automated BingX execution. Manual trading remains available. Next update in 30 minutes.

**Resolution:**

> Automated trading has been restored. The root cause was <summary>. We are monitoring closely and will share a full report within 72 hours.

## Contact Directory

- Platform on-call: `+1-555-0101`
- Trading automation owner: `+1-555-0102`
- Security officer: `+1-555-0103`
- BingX account manager: `bingx@example.com`

Keep this directory in the secure password manager and update quarterly.
