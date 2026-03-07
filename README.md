# TVTelegramBingX

TVTelegramBingX is a small automation toolkit that connects TradingView alerts
with Telegram and optionally executes the resulting orders on BingX futures.
It is designed for hobby traders who want to keep their trading logic inside
TradingView while adding a lightweight automation layer for notifications and
execution.

## Table of contents

1. [Features](#features)
2. [Project layout](#project-layout)
3. [Prerequisites](#prerequisites)
4. [Quick start](#quick-start)
5. [Configuration](#configuration)
6. [Telegram commands](#telegram-commands)
7. [Dynamic take-profit](#dynamic-take-profit)
8. [TradingView alerts](#tradingview-alerts)
9. [Running the webhook standalone](#running-the-webhook-standalone)
10. [Dry-run mode](#dry-run-mode)
11. [Development](#development)
12. [Troubleshooting](#troubleshooting)

## Features

- Receive TradingView alerts and forward them to a Telegram chat.
- Provide inline buttons in Telegram for manual long/short execution.
- Switch between manual confirmation and fully automatic BingX execution.
- Send market orders to BingX using the official REST API.
- Expose a FastAPI webhook that can be called directly from TradingView.
- Watch open positions and submit reduce-only take-profit orders once a configurable price move occurs.
- Apply a configurable stop-loss that closes positions when the price moves against you.

## Project layout

The sections below describe how everything fits together and how to get up and
running.

```
tvtelegrambingx/
├── bot/
│   ├── telegram_bot.py        # Telegram handlers and signal bridge
│   └── trade_executor.py      # Normalises actions and calls BingX
├── integrations/
│   └── bingx_client.py        # Minimal BingX REST wrapper
├── webhook/
│   └── server.py              # TradingView webhook endpoint
└── main.py                    # Application entry point
```

## Prerequisites

- Python 3.10 or newer
- A Telegram bot token (create one via [@BotFather](https://t.me/BotFather))
- Optional: BingX API key & secret for live trading

All Python dependencies are listed in `pyproject.toml`. For a quick manual
install you can run:

```bash
pip install python-telegram-bot httpx fastapi "uvicorn>=0.20"
```

Alternatively, use `pip install -e .` from the repository root to install the
package in editable mode together with its dependencies.

## Quick start

1. Clone the repository and install the dependencies.
2. Copy `.env.example` to `.env` and fill in at least the Telegram settings.
3. Start the application via `./run.sh` or `python -m tvtelegrambingx`.
4. Trigger a test alert from TradingView or use the inline buttons in Telegram
   to verify the connection.

The `run.sh` script automatically loads variables from the `.env` file and
starts both the Telegram bot and (optionally) the webhook.

## Configuration

All configuration happens through environment variables. For every variable
listed below you can either provide the value directly or point to a file that
contains the value using the `_FILE` suffix (e.g. `BINGX_API_KEY_FILE`).

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram Bot API token created via @BotFather. |
| `TELEGRAM_CHAT_ID` | ✅ | Chat/channel ID that receives alerts. |
| `TRADINGVIEW_WEBHOOK_SECRET` | ➖ | Shared secret for webhook requests. Leave empty to accept all requests. |
| `TRADINGVIEW_WEBHOOK_ENABLED` | ➖ | Set to `true` to start the FastAPI webhook (default `false`). |
| `TRADINGVIEW_WEBHOOK_ROUTE` | ➖ | Customise the webhook path (default `/tradingview-webhook`). |
| `TRADINGVIEW_WEBHOOK_HOST` | ➖ | Address uvicorn should bind to (default `0.0.0.0`). |
| `TRADINGVIEW_WEBHOOK_PORT` | ➖ | Listening port (default `443`). |
| `TRADINGVIEW_WEBHOOK_SSL_CERTFILE` | ➖ | Path to the TLS certificate file (aliases: `TLS_CERT_PATH`, `SSL_CERT_PATH`). |
| `TRADINGVIEW_WEBHOOK_SSL_KEYFILE` | ➖ | Path to the TLS private key (aliases: `TLS_KEY_PATH`, `SSL_KEY_PATH`). Required when a certificate is set. |
| `TRADINGVIEW_WEBHOOK_SSL_CA_CERTS` | ➖ | Optional CA bundle for mutual TLS (aliases: `TLS_CA_CERTS_PATH`, `SSL_CA_CERTS_PATH`). |
| `BINGX_API_KEY` / `BINGX_API_SECRET` | ➖ | BingX REST credentials. Mandatory for live trading. |
| `BINGX_BASE_URL` | ➖ | Override the BingX REST base URL (default `https://open-api.bingx.com`). |
| `BINGX_RECV_WINDOW` | ➖ | Customise the BingX `recvWindow` (default `5000`). |
| `BINGX_DEFAULT_QUANTITY` | ➖ | Positionsgröße, die verwendet wird, wenn kein Wert im Signal angegeben ist. |
| `DRY_RUN` | ➖ | Set to `true` to skip order submission (payloads are logged only). |
| `TRADING_DISABLE_WEEKENDS` | ➖ | Deaktiviert eingehende Signale am Wochenende, wenn auf `true` gesetzt. |
| `TRADING_ACTIVE_HOURS` | ➖ | Kommagetrennte Zeitfenster im Format `HH:MM-HH:MM`, in denen der Bot Signale verarbeitet (z. B. `08:00-18:00`). |

Create a `.env` file with the desired values and run the launcher script:

```bash
cp .env.example .env
$EDITOR .env
./run.sh
```

## Telegram commands

| Command | Description |
| --- | --- |
| `/start` | Display a welcome message and the current bot status. |
| `/help` | List all available bot commands. |
| `/status` | Show the latest PnL snapshot and trading configuration. |
| `/auto` | Enable or disable automatic execution of incoming TradingView signals. |
| `/manual` | Alias for `/auto off`. |
| `/botstart` | Resume processing TradingView alerts. |
| `/botstop` | Temporarily ignore incoming alerts. |
| `/margin [USDT]` | Show or update the global order size in USDT. |
| `/leverage [x]` | Show or update the default leverage used for new signals. |
| `/sl [percent]` | Show or set the percentage move that should trigger an automatic stop-loss. |
| `/tp_move [percent]` | Show or set how far the price has to move before the dynamic TP fires. |
| `/tp_sell [percent]` | Show or set what portion of the position to close when the TP triggers. |
| `/tp2_move [percent]` | Configure the price move required for the second dynamic TP. |
| `/tp2_sell [percent]` | Configure what portion to close when the second TP triggers. |
| `/tp3_move [percent]` | Configure the price move required for the third dynamic TP. |
| `/tp3_sell [percent]` | Configure what portion to close when the third TP triggers. |
| `/tp4_move [percent]` | Configure the price move required for the fourth dynamic TP. |
| `/tp4_sell [percent]` | Configure what portion to close when the fourth TP triggers. |
| `/set` | Display all global settings for the current chat at once. |

Each TradingView alert generates a Telegram message with four buttons:

- **🟢 Long öffnen** → `LONG_BUY`
- **⚪️ Long schließen** → `LONG_SELL`
- **🔴 Short öffnen** → `SHORT_SELL`
- **⚫️ Short schließen** → `SHORT_BUY`

## Dynamic take-profit

The bot can automatically reduce profitable positions once they move by a
configured percentage. Set the thresholds per chat with the Telegram commands
above:

- `/tp_move 5` – trigger after a 5 % move in favour of the position
- `/tp_sell 40` – close 40 % of the current position when the trigger is hit
- `/tp2_move 9` – trigger a second TP after a 9 % move (if configured)
- `/tp2_sell 50` – close 50 % of the remaining position on the second trigger
- `/tp3_move 13` – trigger a third TP after a 13 % move (if configured)
- `/tp3_sell 70` – close 70 % of the remaining position on the third trigger
- `/tp4_move 17` – trigger a fourth TP after a 17 % move (if configured)
- `/tp4_sell 80` – close 80 % of the remaining position on the fourth trigger

TP stages need valid move and sell percentages greater than zero to activate.
At least one stage must be configured for the monitor to place orders.
Positions are only reduced once per entry price; opening a new position or
updating the average entry price re-arms the trigger.

Notifications about the automatic close are posted to the configured Telegram
chat so you know exactly when the dynamic take-profit fired.

## Stop-loss

Configure a per-chat stop-loss percentage via `/sl <percent>`. When active, the
bot monitors all open positions and closes them with a reduce-only market order
once the price moves against the entry by the configured percentage. A
notification is sent to the configured Telegram chat whenever a stop-loss is
triggered.

## TradingView alerts

Send alerts to the webhook using the following JSON structure. Provide the
`quantity` that should be traded; alternatively configure a global fallback via
`BINGX_DEFAULT_QUANTITY`.

For inspiration, the repository includes a simple EMA crossover indicator with
an ADX + EMA200-slope filter to avoid seitwärtige Phasen
(`pinescripts/ema_trend_crossover_filtered.pine`). Adapt the alert messages to
match your TradingView setup and forward the resulting BUY/SELL signals to the
webhook.

Use either the legacy `action` field for a single command or the `actions`
array for multiple sequential commands in one alert. Values are normalised
case-insensitively, and comma-separated strings (e.g. `"LONG_BUY, SHORT_BUY"`)
are accepted for convenience.

Optionally include SL/TP overrides per symbol in the payload. These values are
stored for the given `symbol` and override the global `/sl` + `/tp*` settings.
For convenience, simple aliases are accepted too (`sl`, `stop_loss`, `tp`, `tp1`,
`take_profit`):

- `sl_move_percent` (or `sl`, `stop_loss`)
- `tp_move_percent` (or `tp`, `tp1`, `take_profit`), `tp_move_atr`, `tp_sell_percent`
- `tp2_move_percent`, `tp2_move_atr`, `tp2_sell_percent`
- `tp3_move_percent`, `tp3_move_atr`, `tp3_sell_percent`
- `tp4_move_percent`, `tp4_move_atr`, `tp4_sell_percent`

```json
{
  "secret": "12345689",
  "symbol": "LTC-USDT",
  "action": "LONG_BUY",
  "quantity": 0.01,
  "sl_move_percent": 1.5,
  "tp_move_percent": 1.0,
  "tp_sell_percent": 40
}
```

To run two commands at once, provide an `actions` array:

```json
{
  "secret": "12345689",
  "symbol": "LTC-USDT",
  "actions": ["LONG_BUY", "SHORT_BUY"],
  "quantity": 0.01
}
```

Accepted `action` values:

- `LONG_BUY` – open a long position
- `LONG_SELL` – close an existing long position
- `SHORT_SELL` – open a short position
- `SHORT_BUY` – close an existing short position

## Running the webhook standalone

The webhook is optional. If you prefer to process TradingView alerts manually,
leave `TRADINGVIEW_WEBHOOK_ENABLED` unset and only the Telegram bot starts. To
run the webhook, ensure `uvicorn` is installed and export the required secret:

```bash
export TRADINGVIEW_WEBHOOK_ENABLED=true
export TRADINGVIEW_WEBHOOK_SECRET=choose-a-strong-secret
./run.sh
```

The webhook exposes `/tradingview-webhook` for TradingView alerts (plus any
custom route configured via `TRADINGVIEW_WEBHOOK_ROUTE`) and `/health` for
monitoring. Provide the `TRADINGVIEW_WEBHOOK_SSL_CERTFILE` and
`TRADINGVIEW_WEBHOOK_SSL_KEYFILE` variables to enable HTTPS (the server binds to
port `443` by default).

For systems like certbot that expose certificate paths via `TLS_CERT_PATH` and
`TLS_KEY_PATH`, you can rely on those variables directly without duplicating
them. A typical configuration looks like:

```
export TRADINGVIEW_WEBHOOK_ENABLED=true
export TLS_CERT_PATH=/etc/letsencrypt/live/bot.smartconnect.nrw/fullchain.pem
export TLS_KEY_PATH=/etc/letsencrypt/live/bot.smartconnect.nrw/privkey.pem
./run.sh
```

## Dry-run mode

Set `DRY_RUN=true` to disable order submission. The bot will still display
signals in Telegram and log the payloads it would send to BingX.

## Development

This repository is intentionally lightweight. A typical development workflow
looks like this:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
```

The optional `.[dev]` extras include pytest and typing helpers. Linting is kept
minimal; feel free to add your favourite tools locally.

## Troubleshooting

- **Telegram messages are not delivered** – double-check that the bot was added
  to the target chat and that the `TELEGRAM_CHAT_ID` is correct.
- **TradingView requests are rejected** – ensure the webhook secret matches the
  `secret` field in your TradingView alert JSON, or temporarily unset
  `TRADINGVIEW_WEBHOOK_SECRET` for testing.
- **BingX orders fail** – verify that your credentials are valid and that
  `DRY_RUN` is not set to `true`. Check the logs for the exact REST error code.
