# Security Hardening Guide

This document outlines the controls implemented in code and the operational policies required to protect TradingView → Telegram → BingX automation.

## Transport Security

- `FORCE_HTTPS=true` enables FastAPI's HTTPS redirect middleware. Place the backend behind a TLS-terminating load balancer (e.g., AWS ALB, Nginx ingress) and forward the `X-Forwarded-Proto` header so redirects work correctly.
- Configure `ALLOWED_HOSTS` with the list of expected hostnames (comma-separated) to activate FastAPI's `TrustedHostMiddleware` and block Host-header attacks.
- Terminate Telegram bot traffic with a reverse proxy that enforces TLS 1.2+ and modern cipher suites.

## Secret Management and Rotation

- All secrets (TradingView token, Telegram bot token, BingX API keys) live in the process environment. Use a secret manager (AWS Secrets Manager, HashiCorp Vault, etc.) and inject at runtime.
- Rotate secrets at least every 90 days. Implement an automation job that updates the secret store, triggers `systemctl reload tvtelegrambingx-backend`, and notifies administrators.
- Use dual-key rotation for BingX (create new key, deploy, deactivate old key) to avoid downtime.

## Authentication and RBAC

- Telegram bot admin IDs are enforced via `TELEGRAM_ADMIN_IDS`. Only those IDs can toggle auto-trade or manual confirmations.
- Backend endpoints require the TradingView webhook token. Store multiple tokens if running in multi-region setups and rotate using a feature flag (`TRADINGVIEW_WEBHOOK_TOKEN_NEXT`).
- For operator access, place the backend behind an API gateway that enforces SSO (OIDC/SAML) and RBAC per environment (staging, production).

## Database and Infrastructure

- Use managed PostgreSQL with encryption at rest, automatic minor version upgrades, and point-in-time recovery.
- Configure network security groups/firewalls to allow database access only from the backend private subnets.
- Enable audit logging on the database to track schema changes and privileged commands.

## Backup and Restore

- Enable automated daily snapshots of the production database. Retain backups for at least 30 days.
- Test restoration quarterly using a staging environment: restore snapshot, run Alembic migrations, replay a sample of TradingView signals to ensure parity.
- Store offsite backups (e.g., cross-region S3 bucket) for disaster recovery.

## Dependency and Application Security

- GitHub Actions pipeline runs `pip-audit` and `bandit` on every change. Break the build on high severity vulnerabilities or findings.
- Pin dependencies via `pyproject.toml` and review updates monthly.
- Run periodic penetration tests focused on webhook authentication, Telegram bot command abuse, and BingX API rate limiting.

## Incident Handling

- Subscribe to BingX status notifications and TradingView webhook update feeds.
- For suspected compromise, rotate all secrets immediately, invalidate sessions, and review audit logs.
- Follow the [Incident Response Runbook](incident_response.md) for containment and recovery steps.
