# Telegram Bot Deployment (Non-Docker)

This guide describes how to run the Telegram control bot alongside the FastAPI backend without relying on Docker.

## Prerequisites

* Python 3.11 or newer available on the host.
* An API endpoint for the backend (usually `http://127.0.0.1:8000`).
* A Telegram bot token created via [@BotFather](https://core.telegram.org/bots#botfather).
* The Telegram user IDs that are allowed to interact with the bot (comma separated).

## Environment configuration

Create a `.env` file in the repository root or export the variables in your shell:

```bash
TELEGRAM_BOT_TOKEN="123456789:ABC..."
TELEGRAM_ADMIN_IDS="12345678,87654321"
BACKEND_BASE_URL="http://127.0.0.1:8000"
BOT_REPORT_LIMIT=5
BOT_BACKEND_TIMEOUT=15
```

The bot shares the `.env` file with the backend. If you keep the backend configuration there already, simply append the variables above.

## Running locally

Install dependencies inside the `backend` project first:

```bash
cd backend
pip install -e .[dev]
```

Then start the bot:

```bash
python -m bot.main
```

The bot uses long polling by default. Logs are emitted to stdout and include basic auditing information (user ID, username, action).

## systemd service example

Create a unit file at `/etc/systemd/system/tvtelegram-bot.service`:

```ini
[Unit]
Description=TVTelegramBingX Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/tvtelegrambingx
EnvironmentFile=/opt/tvtelegrambingx/.env
ExecStart=/usr/bin/python3 -m bot.main
Restart=on-failure
User=tvtelegram
Group=tvtelegram

[Install]
WantedBy=multi-user.target
```

Reload and enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tvtelegram-bot.service
```

Check logs with `journalctl -fu tvtelegram-bot.service`.

## PM2 process manager (Node.js environments)

If you already use [PM2](https://pm2.keymetrics.io/) to supervise processes:

```bash
pm2 start "python3 -m bot.main" --name tvtelegram-bot --cwd /opt/tvtelegrambingx \
  --interpreter python3 --env .env
pm2 save
```

PM2 will restart the bot on failure and on machine reboot when combined with `pm2 startup`.

## Updating

When new versions are deployed:

1. Pull the latest code and reinstall dependencies if `pyproject.toml` changed.
2. Reload the backend service if required.
3. Restart the bot process (`systemctl restart tvtelegram-bot` or `pm2 restart tvtelegram-bot`).

## Troubleshooting

* **401 Unauthorized from backend** – Ensure the backend is reachable and the `BACKEND_BASE_URL` variable matches its address.
* **Bot ignores commands** – Confirm that the Telegram user ID is listed in `TELEGRAM_ADMIN_IDS`. IDs must be numeric.
* **No reports** – The `/bot/reports` endpoint only returns stored signals. Check that the webhook is ingesting signals correctly.
