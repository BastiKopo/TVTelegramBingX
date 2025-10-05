# TVTelegramBingX

## Prerequisites

- Python 3.10+
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/) library
- [httpx](https://www.python-httpx.org/) for the BingX REST client

Install dependencies:

```bash
pip install python-telegram-bot httpx
```

## Configuration

The bot reads configuration values from environment variables or an optional `.env` file located in the project root. The following variables are supported:

- `TELEGRAM_BOT_TOKEN`: Telegram Bot API token (required).
- `BINGX_API_KEY`: API key for your BingX account (required for BingX integration).
- `BINGX_API_SECRET`: API secret for your BingX account (required for BingX integration).
- `BINGX_BASE_URL`: (Optional) Override the BingX REST base URL. Defaults to `https://open-api.bingx.com`.

You can export the variable directly:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

Or create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
BINGX_API_KEY=your-bingx-api-key
BINGX_API_SECRET=your-bingx-api-secret
#BINGX_BASE_URL=https://open-api.bingx.com
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
