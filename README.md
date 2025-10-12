# TVTelegramBingX

A minimal bridge between TradingView alerts, Telegram notifications, and BingX
futures orders.

The bot receives JSON alerts from TradingView, forwards the signal to Telegram
(including inline buttons for manual execution), and optionally submits the
corresponding market order to BingX. The Telegram chat can switch between
manual and automatic execution at any time.

## Features

- Display TradingView alerts in Telegram.
- Inline buttons to manually open/close long and short positions.
- Auto-trade mode that mirrors TradingView actions on BingX without manual
  intervention.
- Simple FastAPI webhook for TradingView alert delivery.

## Project layout

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

- Python 3.10+
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/) v20+
- [httpx](https://www.python-httpx.org/)
- [FastAPI](https://fastapi.tiangolo.com/) and [uvicorn](https://www.uvicorn.org/)

Install the dependencies with:

```bash
pip install python-telegram-bot httpx fastapi "uvicorn>=0.20"
```

## Configuration

The application is configured via environment variables (or matching `*_FILE`
variants pointing to files that contain the secret):

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram Bot API token. |
| `TELEGRAM_CHAT_ID` | ✅ | Chat/channel ID that receives alerts. |
| `TRADINGVIEW_WEBHOOK_SECRET` | ➖ | Shared secret for webhook requests. Leave empty to accept all requests. |
| `TRADINGVIEW_WEBHOOK_ENABLED` | ➖ | Set to `true` to start the FastAPI webhook (default `false`). |
| `TRADINGVIEW_WEBHOOK_ROUTE` | ➖ | Customise the TradingView webhook path (default `/tradingview-webhook`). |
| `TRADINGVIEW_WEBHOOK_HOST` | ➖ | Webhook bind address. Defaults to `0.0.0.0`. |
| `TRADINGVIEW_WEBHOOK_PORT` | ➖ | Webhook port. Defaults to `443`. |
| `TRADINGVIEW_WEBHOOK_SSL_CERTFILE` | ➖ | Path to the TLS certificate file served by uvicorn (aliases: `TLS_CERT_PATH`, `SSL_CERT_PATH`). |
| `TRADINGVIEW_WEBHOOK_SSL_KEYFILE` | ➖ | Path to the TLS private key file. Required when the certificate is set (aliases: `TLS_KEY_PATH`, `SSL_KEY_PATH`). |
| `TRADINGVIEW_WEBHOOK_SSL_CA_CERTS` | ➖ | Optional CA bundle passed to uvicorn for mutual TLS (aliases: `TLS_CA_CERTS_PATH`, `SSL_CA_CERTS_PATH`). |
| `BINGX_API_KEY` / `BINGX_API_SECRET` | ➖ | BingX REST credentials. Required for live trading. |
| `BINGX_BASE_URL` | ➖ | Override the BingX REST base URL. Defaults to `https://open-api.bingx.com`. |
| `BINGX_RECV_WINDOW` | ➖ | Customise the BingX `recvWindow`. Defaults to `5000`. |
| `BINGX_DEFAULT_QUANTITY` | ➖ | Positionsgröße, die verwendet wird, wenn kein Wert im Signal angegeben ist. |
| `DRY_RUN` | ➖ | Set to `true` to skip order submission (payloads are logged only). |

Create a `.env` file with the desired values and run the launcher script:

```bash
cp .env.example .env
$EDITOR .env
./run.sh
```

## Telegram commands

| Command | Description |
| --- | --- |
| `/start` | Display a welcome message. |
| `/auto` | Enable automatic execution of incoming TradingView signals. |
| `/manual` | Switch back to manual mode (signals are displayed but not executed automatically). |

Each TradingView alert generates a Telegram message with four buttons:

- **🟢 Long öffnen** → `LONG_BUY`
- **⚪️ Long schließen** → `LONG_SELL`
- **🔴 Short öffnen** → `SHORT_SELL`
- **⚫️ Short schließen** → `SHORT_BUY`

## TradingView alerts

Send alerts to the webhook using the following JSON structure. The `action`
field controls both the Telegram display and the BingX order type. Provide the
`quantity` that should be traded; alternatively configure a global fallback via
`BINGX_DEFAULT_QUANTITY`.

```json
{
  "secret": "12345689",
  "symbol": "LTC-USDT",
  "action": "LONG_BUY",
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
