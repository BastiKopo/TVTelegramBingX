# TVTelegramBingX

## Prerequisites

- Python 3.10+
- [python-telegram-bot](https://docs.python-telegram-bot.org/en/stable/) library

Install dependencies:

```bash
pip install python-telegram-bot
```

## Configuration

The bot reads configuration values from environment variables or an optional `.env` file located in the project root. The following variables are supported:

- `TELEGRAM_BOT_TOKEN`: Telegram Bot API token.

You can export the variable directly:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

Or create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
```

## Running the bot

Run the Telegram bot locally:

```bash
python -m bot.telegram_bot
```

When the bot starts it logs its initialization status and exposes the following commands:

- `/status` – Confirms that the bot is online.
- `/help` – Lists available commands.
- `/report` – Placeholder for future trade reports.
- `/margin` – Placeholder for margin information.
- `/leverage` – Placeholder for leverage settings.

Financial data responses currently return placeholder messages until the BingX integration is implemented.
