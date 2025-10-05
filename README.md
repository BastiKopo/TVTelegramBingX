# TVTelegramBingX

## Prerequisites

- Python 3.10+
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/) library
- [httpx](https://www.python-httpx.org/) for the BingX REST client
- [FastAPI](https://fastapi.tiangolo.com/) and [uvicorn](https://www.uvicorn.org/) for the webhook server

Install dependencies:

```bash
pip install python-telegram-bot httpx fastapi uvicorn
```

## Configuration

The bot reads configuration values from environment variables or an optional `.env` file located in the project root. The following variables are supported:

- `TELEGRAM_BOT_TOKEN`: Telegram Bot API token.
- `BINGX_API_KEY`: API key for your BingX account (optional, enables financial commands).
- `BINGX_API_SECRET`: API secret for your BingX account (optional, enables financial commands).
- `BINGX_BASE_URL`: (Optional) Override the BingX REST base URL. Defaults to `https://open-api.bingx.com`.
- `TRADINGVIEW_WEBHOOK_SECRET`: Shared secret used to authenticate TradingView alerts.
- `TELEGRAM_ALERT_CHAT_ID`: Chat ID that receives webhook alert notifications.

You can export the variable directly:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

Or create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
BINGX_API_KEY=your-bingx-api-key
BINGX_API_SECRET=your-bingx-api-secret
TRADINGVIEW_WEBHOOK_SECRET=your-shared-secret
TELEGRAM_ALERT_CHAT_ID=123456789
```

## Running the bot

Run the Telegram bot locally:

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

## TradingView webhook server

The project ships with a lightweight FastAPI application that exposes an HTTPS-compatible webhook endpoint for TradingView alerts. To run the server locally, configure the environment variables described above and start `uvicorn`:

```bash
uvicorn webhook.server:app --host 0.0.0.0 --port 8000
```

> **Note:** The webhook expects HTTPS traffic in production. When running locally you can use a tunnelling service (such as ngrok or Cloudflare Tunnel) or configure TLS termination directly in `uvicorn` via the `--ssl-keyfile` and `--ssl-certfile` options.

### Endpoint

- **URL:** `https://<your-domain>/tradingview-webhook`
- **Method:** `POST`
- **Authentication:** Provide the shared secret either in the JSON payload (`"secret"`) or via the `X-TradingView-Secret` header.

### Example TradingView alert payload

Configure your TradingView alert message to send JSON similar to the following:

```json
{
  "secret": "your-shared-secret",
  "ticker": "BINANCE:BTCUSDT",
  "action": "buy",
  "price": {{close}},
  "message": "Moving average crossover detected",
  "strategy": {
    "position_size": {{strategy.position_size}},
    "order_id": "{{strategy.order.id}}"
  }
}
```

Every valid alert is forwarded to the configured Telegram chat. The notification includes the optional message plus a formatted breakdown of the payload so you can quickly assess the signal or initiate BingX order logic.
