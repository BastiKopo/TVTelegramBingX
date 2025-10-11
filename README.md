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
- `BINGX_BASE_URL` / `BINGX_BASE`: (Optional) Override the BingX REST base URL. Defaults to `https://open-api.bingx.com`.
- `BINGX_RECV_WINDOW`: (Optional) Customise the BingX `recvWindow` in milliseconds. Defaults to `5000`.
- `POSITION_MODE`: Configure the expected BingX position mode (`hedge` or `oneway`). Defaults to `hedge`.
- `MARGIN_MODE`: Futures margin mode applied to new symbols (`isolated` or `cross`). Defaults to `isolated`.
- `GLOBAL_MARGIN_USDT`: Default USDT budget used to size orders when no explicit quantity is supplied.
- `GLOBAL_LEVERAGE`: Global leverage applied during sizing and the first trade per symbol. Defaults to `10` when omitted.
- `GLOBAL_TIF`: Default time-in-force used for limit orders when none is provided. Defaults to `GTC`.
- `DRY_RUN`: Set to `true`/`1` to disable order submission and only log payloads.
- `WHITELIST` / `SYMBOL_WHITELIST`: Comma-separated list of allowed symbols (e.g. `BTC-USDT,ETH-USDT`). Orders for other symbols are rejected.
- `SYMBOL_MIN_QTY` / `SYMBOL_MAX_QTY`: Optional per-symbol quantity guards formatted as `SYMBOL:VALUE` pairs separated by commas (e.g. `BTC-USDT:0.001,ETH-USDT:0.01`).
- `SYMBOL_META`: Optional JSON object providing fallback instrument metadata such as `stepSize`/`minQty` for each symbol, e.g. `{"BTC-USDT":{"stepSize":"0.001"}}`.
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
#BINGX_BASE=https://open-api.bingx.com
#BINGX_RECV_WINDOW=5000
#POSITION_MODE=hedge
#MARGIN_MODE=isolated
#GLOBAL_MARGIN_USDT=100
#GLOBAL_LEVERAGE=10
#GLOBAL_TIF=GTC
#DRY_RUN=0
#WHITELIST=BTC-USDT,ETH-USDT
#SYMBOL_MIN_QTY=BTC-USDT:0.001
#SYMBOL_MAX_QTY=BTC-USDT:5
#SYMBOL_META={"BTC-USDT":{"stepSize":"0.001"},"ETH-USDT":{"stepSize":"0.01"}}

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

## Globale Trading-Defaults

Set the global futures defaults once via the environment and the bot reuses them
for every alert, manual command, and newly traded symbol:

```env
POSITION_MODE=hedge
MARGIN_MODE=isolated
GLOBAL_MARGIN_USDT=100
GLOBAL_LEVERAGE=10
GLOBAL_TIF=GTC
```

On the first run without an existing `bot_state.json`, these values seed the
runtime state. Subsequent changes through Telegram commands are persisted so you
can fine-tune the defaults without editing the `.env` file. The margin mode and
leverage are automatically synchronised with BingX the first time a symbol is
traded; later orders skip the setup.

When neither TradingView nor Telegram provide an explicit quantity the bot
derives it from the global budget using the current mark price and step size:

```
qty = floor_to_step((GLOBAL_MARGIN_USDT * GLOBAL_LEVERAGE) / mark_price)
```

If the result rounds down to zero the bot responds with a descriptive error so
you can increase the budget or leverage.

## Running the bot

Run the Telegram bot locally:

```bash
./run.sh
```

The script runs the Telegram bot without importing any webhook dependencies. FastAPI and uvicorn are only needed when `TRADINGVIEW_WEBHOOK_ENABLED=true`.

## Offline smoke test for manual/autotrade

If you only want to confirm that both the manual execution helper and the
autotrade flow prepare valid BingX payloads without touching the real API, run
the dedicated smoke test script. It uses an in-memory BingX client stub and
prints the assembled orders to stdout:

```bash
python scripts/trading_flow_smoke_test.py
```

Successful output shows the generated payloads for a manual `BTCUSDT` order and
an autotrade `ETHUSDT` example so you can validate the configuration locally
before connecting the bot to BingX.

You can also invoke the module directly if you prefer:

```bash
python -m bot.telegram_bot
```

## BingX Swap V2 Order Checklist

Bevor Änderungen am BingX-Orderflow ausgeliefert werden, häng Codex die
folgende Mini-Checkliste samt Schnelltests an, damit er das Routing direkt
gegenprüfen kann:

### TL;DR-Checkliste (sollte nach dem Patch stimmen)

* BASE: `https://open-api.bingx.com`
* ORDER-Pfad: `/openApi/swap/v2/trade/order`
* Methode: `POST`
* Content-Type: `application/x-www-form-urlencoded`
* Body: alphabetisch sortierte Query + `signature=…` (HMAC-SHA256)
* **Kein** JSON-Body, **kein** Spot-/V1-Pfad

### Schnelltests im Repo

```bash
# 1) Stelle sicher, dass nirgendwo falsch geroutet wird:
grep -RInE "bingx|openApi|swap|trade/order|spot|v1|v2" -n .

# 2) Gefährliche alte Routen aufspüren:
grep -RInE "/api/v1|/openApi/spot|/swap/v1" -n .

# 3) Prüfen, dass x-www-form-urlencoded wirklich gesetzt ist:
grep -RIn "Content-Type" -n | grep -i urlencoded
```

### Smoke-Call aus dem Bot (soll wie Bash aussehen)

Beim Senden **immer** so loggen (und im Log vergleichen):

```
→ POST https://open-api.bingx.com/openApi/swap/v2/trade/order
→ BODY: positionSide=LONG&quantity=1&recvWindow=5000&side=BUY&symbol=LTC-USDT&timestamp=...&type=MARKET&signature=<redacted>
HTTP 200 {"code":0,...}
```

### Optionaler Schutz (1 Zeile)

* Bei API-Code `100400` sofort werfen:

```ts
if (apiCode === 100400) throw new Error("Wrong endpoint: use POST https://open-api.bingx.com/openApi/swap/v2/trade/order with x-www-form-urlencoded.");
```

When the bot starts it logs its initialization status and exposes the following commands:

- `/status` – Confirms that the bot is online.
- `/help` – Lists available commands.
- `/report` – Shows an overview of your BingX balance and open positions.
- `/margin <USDT>` – Sets the global sizing budget that is translated into contract quantity via mark prices and leverage.
- `/lev <x>` – Updates the shared leverage for long and short trades. The value is synchronised automatically per symbol on demand.
- `/mode <hedge|oneway>` – Switches the account position mode. Hedge mode unlocks `/long` and `/short` while one-way uses `/open`.
- `/mgnmode <isolated|cross>` – Configures how new symbols are initialised when orders are submitted for the first time.
- `/tif <GTC|IOC|FOK>` – Adjusts the default time-in-force applied to limit orders when no override is supplied.
- `/buy <Symbol> <Menge> <LONG|SHORT>` – Opens a position immediately using a market order.
- `/sell <Symbol> <Menge> <LONG|SHORT>` – Closes an existing position using reduce-only market orders.
- `/long <Symbol> [--qty <Menge>] [--limit <Preis>] [--tif <GTC|IOC|FOK>] [--clid <ID>]` – Hedge-mode shortcut that opens a long position using the global sizing logic unless `--qty` overrides it.
- `/short <Symbol> [--qty <Menge>] [--limit <Preis>] [--tif <GTC|IOC|FOK>] [--clid <ID>]` – Hedge-mode shortcut to open a short position.
- `/open <Symbol> [--qty <Menge>] [--limit <Preis>] [--tif <GTC|IOC|FOK>] [--clid <ID>]` – One-way shortcut that submits BUY/BOTH orders sized via the global defaults.
- `/close long|short <Symbol> [--qty <Menge>] [--limit <Preis>] [--tif <GTC|IOC|FOK>] [--clid <ID>]` – Hedge-mode reduce-only commands; omit the direction in one-way mode to close the combined position.
- `/close <Symbol> [--qty <Menge>] [--limit <Preis>] [--tif <GTC|IOC|FOK>] [--clid <ID>]` – One-way reduce-only shortcut mirroring `/open`.

When using `--margin`, the bot converts the budget (in USDT) into the correct contract quantity using the BingX mark price, leverage and step size filters so the resulting order remains valid.
- `/halt` / `/resume` – Toggle the dry-run kill switch at runtime.

Financial commands require valid BingX API credentials. If credentials are missing, the bot replies with a helpful reminder.

## TradingView webhook integration

To relay TradingView alerts to Telegram, enable the webhook service:

1. Create or update your `.env` file with the TradingView variables shown above. Ensure the certificate and key paths point to valid files. Self-signed certificates work for testing as long as TradingView can reach the public endpoint.
2. Run `./run.sh`. When `TRADINGVIEW_WEBHOOK_ENABLED` is `true`, the script starts both the Telegram bot and a FastAPI webhook service via `uvicorn` with TLS enabled. Ensure you have installed FastAPI and uvicorn before enabling the webhook. The script now checks for the `uvicorn` binary and aborts immediately if it is missing or if the webhook server cannot start, preventing the bot from running without the HTTPS endpoint.
3. Expose port `8443` (or your configured `TRADINGVIEW_WEBHOOK_PORT`) publicly so that TradingView can reach `https://<your-domain>/tradingview-webhook`.
4. In TradingView, configure a webhook alert and include the shared secret either in the JSON payload (e.g. `{ "passphrase": "choose-a-strong-secret", "message": "..." }`) or as an `X-Tradingview-Secret` header if your infrastructure supports custom headers. The webhook accepts both TradingView's default `passphrase` field and a custom `secret`/`password` property.

Validated alerts are forwarded to the Telegram bot. When `TELEGRAM_CHAT_ID` is set, the bot automatically sends a formatted message to that chat and keeps a short in-memory history that can be inspected by custom handlers.

The webhook exposes an unauthenticated health endpoint at `GET /webhook/health`. TradingView's `Send Test` button and external monitoring tools can call this URL to verify that the service is reachable before sending live alerts. Every POST request is logged with the caller IP, user-agent, content type and a short body preview so you can troubleshoot malformed payloads quickly.【F:webhook/server.py†L75-L142】

### TradingView webhook URL format

When the webhook service is enabled, uvicorn binds to `https://<host>:<port>/tradingview-webhook`, where `<host>` and `<port>` come from `TRADINGVIEW_WEBHOOK_HOST` (defaults to `0.0.0.0`) and `TRADINGVIEW_WEBHOOK_PORT` (defaults to `8443`). After exposing the service publicly (e.g. via reverse proxy or port forwarding), configure TradingView with the fully qualified HTTPS URL that resolves to your server. For example:

```
https://alerts.example.com:8443/tradingview-webhook
```

If you terminate TLS in a reverse proxy that forwards traffic to the bot, use the externally visible hostname and port exposed by the proxy (e.g. `https://alerts.example.com/tradingview-webhook`). The webhook accepts both `application/json` and `text/plain` payloads. Text payloads are parsed as `key=value` pairs (separated by semicolons, ampersands, or line breaks), which matches TradingView's default webhook test format. Include the shared secret either in the headers or as part of the payload, for example:

```json
{
  "passphrase": "choose-a-strong-secret",
  "message": "Strategy triggered"
}
```

Any payload that passes secret validation is queued and forwarded to Telegram handlers. Missing or mismatched secrets still result in an HTTP 403 response, but malformed or unparsable payloads now receive a `200 OK` response with status `ignored`. The bot forwards an error notification to Telegram (and skips autotrade) so you can fix the alert without TradingView retrying indefinitely.【F:webhook/server.py†L75-L142】【F:bot/telegram_bot.py†L3321-L3369】

### Quick self-test

Once the webhook is running you can run simple smoke tests from the command line:

```bash
curl -s https://<host>:<port>/webhook/health

curl -s -X POST https://<host>:<port>/tradingview-webhook \
  -H "Content-Type: text/plain" \
  --data 'symbol=LTCUSDT;action=LONG_OPEN;margin_usdt=5;lev=50;alert_id=local-test;bar_time=2024-01-01T00:00:00Z;secret=<your-secret>'
```

The POST call should return `{"status":"accepted"}` almost instantly. The bot logs the request and forwards a signal to Telegram when the shared secret matches.【F:webhook/server.py†L109-L142】 Duplicate alerts are ignored for 30 seconds based on symbol, direction and bar timestamp to protect against double delivery from TradingView.【F:webhook/payloads.py†L9-L204】

### TradingView alert payload format

When autotrade is enabled, the bot turns valid TradingView alerts into BingX orders. The payload can contain any additional fields you need for your own logging, but the following keys control how the order is created:

| Field | Required | Accepted aliases | Notes |
| --- | --- | --- | --- |
| `symbol` | ✅ | `ticker`, `pair`, `base`, `market`, strategy `symbol` | Must resolve to the BingX symbol (e.g. `BTCUSDT`). |
| `side` | ✅ | `signal`, `action`, `direction` | `buy`/`long` becomes `BUY`, `sell`/`short` becomes `SELL`. |
| `quantity` | optional | `qty`, `size`, `positionSize`, `amount`, `orderSize` | Explicit contract quantity to send to BingX. When omitted the bot sizes the trade using the global defaults. |
| `margin` | optional | `margin_usdt`, `marginUsdt`, `marginAmount`, `marginValue` | Overrides the global margin budget for a single order. |
| `lev` | optional | `leverage`, `leverageValue` | Overrides the leverage used for the quantity calculation. Falls back to `GLOBAL_LEVERAGE` when omitted. |
| `orderType` | optional | `type` | Defaults to `MARKET`. Use `LIMIT` together with `price`/`orderPrice` for limit orders. |
| `price` | optional | `orderPrice` | Only used when `orderType` is not `MARKET`. |
| `tif` | optional | `time_in_force`, `timeInForce` | When `orderType` is `LIMIT`, overrides the time-in-force. Defaults to `GLOBAL_TIF` when omitted. |
| `reduceOnly` | optional | `reduce_only`, `closePosition` | Converted to a boolean to send reduce-only orders. |
| `positionSide` | optional | `position_side`, `position`, `posSide` | Forces `LONG` or `SHORT`. Otherwise the bot infers it from the trade direction. |
| `clientOrderId` | optional | `client_id`, `id` | Forwarded to BingX unchanged. |

> *If the calculated quantity rounds down to zero (e.g. because the global margin is too small for the current price) the bot rejects the alert with a Telegram warning.

Margin mode, margin coin, and leverage always come from the persisted bot state which is seeded from the global defaults. Any values in the TradingView payload are ignored so BingX receives the configuration managed via Telegram (`margin_mode`, `margin_asset`, leverage).【F:bot/telegram_bot.py†L1526-L1706】

An example alert for a market order therefore looks like this:

```json
{
  "secret": "choose-a-strong-secret",
  "symbol": "LTCUSDT",
  "action": "LONG_OPEN",
  "order_type": "MARKET",
  "alert_id": "tv-ltc-long-open"
}
```

And a limit order that closes a long position:

```json
{
  "secret": "choose-a-strong-secret",
  "symbol": "LTCUSDT",
  "action": "LONG_CLOSE",
  "order_type": "LIMIT",
  "price": "{{close}}",
  "qty_override": "2.0",
  "tif": "IOC",
  "alert_id": "tv-ltc-long-close"
}
```

The bot automatically merges these alerts with the margin configuration stored in `state.json` before invoking the BingX client, so you only maintain margin and leverage settings in one place.【F:bot/telegram_bot.py†L1588-L1669】

### Obtaining and installing Let's Encrypt certificates

If TradingView reports that the webhook certificate is invalid, issue a trusted TLS certificate via [Let's Encrypt](https://letsencrypt.org/). The steps below use the official Certbot client on Ubuntu/Debian systems, but any ACME client that generates a certificate/key pair on disk will work.

1. **Install Certbot**:

   ```bash
   sudo apt update
   sudo apt install certbot
   ```

   For Nginx or Apache front-ends, install the plugin package as well (e.g. `sudo apt install python3-certbot-nginx`).

2. **Request a certificate** for the public domain that TradingView will call. For a standalone TLS certificate, stop any service that already binds to port 80/443 and run:

   ```bash
   sudo certbot certonly --standalone -d example.com -d www.example.com
   ```

   Replace the domains with the hostname(s) that resolve to your webhook server. Certbot stores the certificate and key under `/etc/letsencrypt/live/<domain>/` by default.

3. **Point the bot to the certificate files**. Update your environment so `TLS_CERT_PATH` references the `fullchain.pem` bundle and `TLS_KEY_PATH` references `privkey.pem`:

   ```env
   TLS_CERT_PATH=/etc/letsencrypt/live/example.com/fullchain.pem
   TLS_KEY_PATH=/etc/letsencrypt/live/example.com/privkey.pem
   ```

   These variables are loaded by `config.get_settings()` and passed to the uvicorn server when `TRADINGVIEW_WEBHOOK_ENABLED=true`, so no additional code changes are required.【F:config.py†L55-L106】【F:tvtelegrambingx/main.py†L52-L120】

4. **Reload the service** that runs `./run.sh` (systemd, Docker container, etc.) so the new environment variables are picked up. The webhook server will now present the trusted Let's Encrypt certificate.

5. **Renew automatically**. Let's Encrypt certificates expire every 90 days. Set up a cron job or systemd timer to run `certbot renew` daily. Certbot only renews certificates that are within the renewal window and will keep the existing file paths, so the bot can continue using the same `TLS_CERT_PATH` and `TLS_KEY_PATH` values.

If you terminate TLS in a reverse proxy (e.g. Nginx) instead of uvicorn directly, install the Let's Encrypt certificate in the proxy and forward plain HTTP traffic from the proxy to the application. In that setup, disable TLS inside the bot container by omitting `TLS_CERT_PATH`/`TLS_KEY_PATH` and letting the proxy handle HTTPS.
