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
8. [AI Gatekeeper (optional)](#ai-gatekeeper-optional)
9. [TradingView alerts](#tradingview-alerts)
10. [Running the webhook standalone](#running-the-webhook-standalone)
11. [Dry-run mode](#dry-run-mode)
12. [Development](#development)
13. [Troubleshooting](#troubleshooting)

## Features

- Receive TradingView alerts and forward them to a Telegram chat.
- Provide inline buttons in Telegram for manual long/short execution.
- Switch between manual confirmation and fully automatic BingX execution.
- Send market orders to BingX using the official REST API.
- Expose a FastAPI webhook that can be called directly from TradingView.
- Optional AI gatekeeper to approve or block open signals per asset.
- Watch open positions and submit reduce-only take-profit orders once a configurable price move occurs.
- Apply a configurable stop-loss that closes positions when the price moves against you.

## Project layout

The sections below describe how everything fits together and how to get up and
running.

```
tvtelegrambingx/
├── ai/
│   └── gatekeeper.py          # Optional AI gatekeeper + feedback store
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
| `AI_UNIVERSE` | ➖ | Kommagetrennte Liste der Assets, die von der AI bewertet werden (z. B. `BTC-USDT,ETH-USDT`). |
| `AI_AUTONOMOUS_ENABLED` | ➖ | Aktiviert autonomes AI-Trading (Standard `false`). |
| `AI_AUTONOMOUS_INTERVAL_SECONDS` | ➖ | Intervall für autonome AI-Checks (Standard `300`). |
| `AI_AUTONOMOUS_KLINE_INTERVAL` | ➖ | Kline-Intervall für autonome Signale (Standard `15m`). |
| `AI_AUTONOMOUS_KLINE_LIMIT` | ➖ | Anzahl der Kerzen für autonome Signale (Standard `60`). |
| `AI_AUTONOMOUS_DRY_RUN` | ➖ | Nur Signale loggen, keine Orders senden (Standard `true`). |
| `AI_FILTER_RSI_ENABLED` | ➖ | RSI-Filter aktivieren (Standard `false`). |
| `AI_FILTER_ATR_ENABLED` | ➖ | ATR-Filter aktivieren (Standard `false`). |
| `AI_FILTER_TREND_ENABLED` | ➖ | EMA200-Trendfilter aktivieren (Standard `false`). |
| `AI_FILTER_RSI_OVERBOUGHT` | ➖ | RSI Overbought-Grenze (Standard `70`). |
| `AI_FILTER_RSI_OVERSOLD` | ➖ | RSI Oversold-Grenze (Standard `30`). |
| `AI_FILTER_ATR_MIN_PERCENT` | ➖ | Mindest-ATR in Prozent (Standard `0.3`). |

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
| `/ai_universe` | Limit AI checks to a list of assets. |
| `/ai_autonomous` | Enable or disable autonomous AI trading. |
| `/ai_autonomous_interval` | Set the autonomous AI loop interval in seconds. |
| `/ai_autonomous_dry` | Toggle autonomous AI dry-run mode. |
| `/ai_autonomous_status` | Show autonomous AI status and stats. |
| `/ai_filter_rsi` | RSI Filter on/off oder Grenzen setzen. |
| `/ai_filter_atr` | ATR Filter on/off oder Mindestwert setzen. |
| `/ai_filter_trend` | EMA200 Trendfilter on/off. |
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

## AI Autonomous (optional)

The autonomous AI mode generates signals from candlestick data without
TradingView. It uses a simple SMA crossover (5 vs 20) on recent klines and
dispatches signals through the existing TradingView pipeline, so manual
TradingView alerts continue to work in parallel.

Use `/ai_autonomous on` to enable, `/ai_autonomous_dry on` to dry-run, and
`/ai_autonomous_status` to see counters such as generated, dispatched, and
skipped signals.

When dry-run is enabled the bot sends a Telegram notification for each
autonomous signal that would have been executed, plus blocks caused by filters.

Optional filters:
- RSI filter (default 70/30) to avoid overbought longs / oversold shorts.
- ATR filter to require minimum volatility.
- EMA200 trend filter (longs above EMA200, shorts below).

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

```json
{
  "secret": "12345689",
  "symbol": "LTC-USDT",
  "action": "LONG_BUY",
  "quantity": 0.01
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
