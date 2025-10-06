# TVTelegramBingX

## Prerequisites

- Python 3.10+
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/) library
- [httpx](https://www.python-httpx.org/) for the BingX REST client
- [FastAPI](https://fastapi.tiangolo.com/) and [uvicorn](https://www.uvicorn.org/) (version 0.20 or newer) **when the TradingView webhook is enabled**

Install dependencies:

```bash
pip install python-telegram-bot httpx

# Install FastAPI dependencies only if you plan to enable the webhook
pip install fastapi "uvicorn>=0.20"
```

## Configuration

The bot reads configuration values from environment variables or an optional `.env` file located in the project root. The following variables are supported:

- `TELEGRAM_BOT_TOKEN`: Telegram Bot API token (required).
- `BINGX_API_KEY`: API key for your BingX account (required for BingX integration).
- `BINGX_API_SECRET`: API secret for your BingX account (required for BingX integration).
- `BINGX_BASE_URL`: (Optional) Override the BingX REST base URL. Defaults to `https://open-api.bingx.com`.
- `TELEGRAM_CHAT_ID`: Optional chat or channel ID used to broadcast TradingView alerts automatically.
- `TRADINGVIEW_WEBHOOK_ENABLED`: Set to `true` to launch the HTTPS webhook service.
- `TRADINGVIEW_WEBHOOK_SECRET`: Shared secret required in TradingView webhook requests.
- `TLS_CERT_PATH` / `TLS_KEY_PATH`: Paths to the TLS certificate and key files served by `uvicorn`.
- `TRADINGVIEW_WEBHOOK_HOST` / `TRADINGVIEW_WEBHOOK_PORT` (optional): Override the bind address for the webhook server. Defaults to `0.0.0.0:8443`.

You can export the variable directly:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

Or create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
BINGX_API_KEY=your-bingx-api-key
BINGX_API_SECRET=your-bingx-api-secret
TELEGRAM_CHAT_ID=your-telegram-chat-id
#BINGX_BASE_URL=https://open-api.bingx.com

# TradingView webhook configuration (optional)
TRADINGVIEW_WEBHOOK_ENABLED=true
TRADINGVIEW_WEBHOOK_SECRET=choose-a-strong-secret
TLS_CERT_PATH=/path/to/certificate.pem
TLS_KEY_PATH=/path/to/private-key.pem
#TRADINGVIEW_WEBHOOK_HOST=0.0.0.0
#TRADINGVIEW_WEBHOOK_PORT=8443
```

You can also duplicate the provided `.env.example` file and adjust the values before running `./run.sh`:

```bash
cp .env.example .env
$EDITOR .env
```

## Running the bot

Run the Telegram bot locally:

```bash
./run.sh
```

The script runs the Telegram bot without importing any webhook dependencies. FastAPI and uvicorn are only needed when `TRADINGVIEW_WEBHOOK_ENABLED=true`.

You can also invoke the module directly if you prefer:

```bash
python -m bot.telegram_bot
```

When the bot starts it logs its initialization status and exposes the following commands:

- `/status` – Confirms that the bot is online.
- `/help` – Lists available commands.
- `/report` – Shows an overview of your BingX balance and open positions.
- `/margin` – Retrieves the latest margin breakdown from BingX.
- `/leverage` – Displays leverage details for currently open positions.

Financial commands require valid BingX API credentials. If credentials are missing, the bot replies with a helpful reminder.

## TradingView webhook integration

To relay TradingView alerts to Telegram, enable the webhook service:

1. Create or update your `.env` file with the TradingView variables shown above. Ensure the certificate and key paths point to valid files. Self-signed certificates work for testing as long as TradingView can reach the public endpoint.
2. Run `./run.sh`. When `TRADINGVIEW_WEBHOOK_ENABLED` is `true`, the script starts both the Telegram bot and a FastAPI webhook service via `uvicorn` with TLS enabled. Ensure you have installed FastAPI and uvicorn before enabling the webhook. The script now checks for the `uvicorn` binary and aborts immediately if it is missing or if the webhook server cannot start, preventing the bot from running without the HTTPS endpoint.
3. Expose port `8443` (or your configured `TRADINGVIEW_WEBHOOK_PORT`) publicly so that TradingView can reach `https://<your-domain>/tradingview-webhook`.
4. In TradingView, configure a webhook alert and include the shared secret either in the JSON payload (e.g. `{ "secret": "choose-a-strong-secret", "message": "..." }`) or as an `X-Tradingview-Secret` header if your infrastructure supports custom headers.

Validated alerts are forwarded to the Telegram bot. When `TELEGRAM_CHAT_ID` is set, the bot automatically sends a formatted message to that chat and keeps a short in-memory history that can be inspected by custom handlers.
