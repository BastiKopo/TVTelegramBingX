# Production Deployment Guide

This guide describes how to deploy the TVTelegramBingX backend and Telegram bot without Docker.

## Prerequisites

- Ubuntu 22.04 LTS servers (one for backend, one for bot) with systemd.
- Python 3.11 installed via `pyenv` or distribution packages.
- Access to managed PostgreSQL, RabbitMQ (if using broker publisher), and Redis (optional for caching).
- Secrets stored in Vault or AWS Secrets Manager.

## Backend Deployment Steps

1. **Provision virtual environment**
   ```bash
   python3.11 -m venv /opt/tvtelegrambingx-backend
   source /opt/tvtelegrambingx-backend/bin/activate
   pip install --upgrade pip
   pip install -e /srv/tvtelegrambingx/backend[dev]
   ```
2. **Configure environment** – Create `/etc/tvtelegrambingx/backend.env` containing all required variables (database URL, tokens, telemetry settings). Restrict permissions to `tvtelegrambingx` system user.
3. **Migrations**
   ```bash
   source /opt/tvtelegrambingx-backend/bin/activate
   export $(grep -v '^#' /etc/tvtelegrambingx/backend.env | xargs)
   alembic upgrade head
   ```
4. **Systemd service** – Install `/etc/systemd/system/tvtelegrambingx-backend.service`:
   ```ini
   [Unit]
   Description=TVTelegramBingX Backend
   After=network-online.target

   [Service]
   User=tvtelegrambingx
   EnvironmentFile=/etc/tvtelegrambingx/backend.env
   ExecStart=/opt/tvtelegrambingx-backend/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8443 --proxy-headers
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```
   Reload systemd and start the service.

5. **Networking** – Place the service behind an HTTPS reverse proxy (Nginx/Envoy) that terminates TLS and forwards `X-Forwarded-Proto` and `X-Forwarded-For` headers.

## Telegram Bot Deployment Steps

1. **Virtual environment** – repeat the venv setup at `/opt/tvtelegrambingx-bot` and install `pip install -e /srv/tvtelegrambingx/backend[dev]` (bot shares dependencies).
2. **Environment file** – `/etc/tvtelegrambingx/bot.env` with Telegram token, admin IDs, backend URL, telemetry settings.
3. **Systemd service** – `/etc/systemd/system/tvtelegrambingx-bot.service`:
   ```ini
   [Unit]
   Description=TVTelegramBingX Telegram Bot
   After=network-online.target

   [Service]
   User=tvtelegrambingx
   EnvironmentFile=/etc/tvtelegrambingx/bot.env
   ExecStart=/opt/tvtelegrambingx-bot/bin/python -m bot.main
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```
4. **Firewall** – Allow outbound HTTPS to Telegram API and backend inbound from trusted proxies only.

## Zero-Downtime Strategy

- Run rolling deployments: bring up new backend instance, wait for health check success, then cut traffic.
- Use PostgreSQL read replicas for migrations if downtime risk exists; run migrations in shadow mode first.
- For the bot, use Telegram's `setWebhook` maintenance message or temporarily disable auto-trade while updating.

## Post-Deployment Validation

1. Run integration smoke test (see `tests/test_end_to_end_signal_flow.py`) against staging, then production with dry-run BingX credentials.
2. Confirm metrics are streaming to Prometheus and spans to Tempo.
3. Trigger `/status` and `/reports` via Telegram to verify bot responsiveness.
4. Review logs for warnings/errors during deployment window.

## Rollback

- Re-deploy previous Git commit and rerun Alembic `downgrade` if schema changes were introduced.
- Restore environment file from backup if misconfiguration suspected.
- Re-enable auto trading only after successful rollback validation.
