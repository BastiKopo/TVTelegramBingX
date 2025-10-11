# TradingView Alert Examples

This guide collects ready-to-use payloads for TradingView alerts that work with the TVTelegramBingX webhook integration. They demonstrate how to send buy/long and sell/short orders with optional quantity overrides and limit settings.

## Market buy (open long)

Use this payload to open a long position with a market order. Replace the placeholders before saving the alert in TradingView:

```json
{
  "secret": "<your-shared-secret>",
  "symbol": "BTCUSDT",
  "action": "LONG_OPEN",
  "order_type": "MARKET",
  "quantity": "0.005",
  "alert_id": "tv-btc-long-open"
}
```

- `secret`: Must match `TRADINGVIEW_WEBHOOK_SECRET`.
- `symbol`: Trading pair on BingX (e.g. `BTCUSDT`).
- `action`: Use `LONG_OPEN`/`LONG_CLOSE` or aliases like `buy`/`sell`. The payload is case-insensitive.
- `order_type`: `MARKET` executes immediately.
- `quantity`: Optional override; omit to use the default position sizing configured in Telegram.
- `alert_id`: Free-form identifier that helps deduplicate alerts.

## Market sell (close long / open short)

To close an existing long or flip short with a market order:

```json
{
  "secret": "<your-shared-secret>",
  "symbol": "BTCUSDT",
  "action": "LONG_CLOSE",
  "order_type": "MARKET",
  "reduce_only": true,
  "alert_id": "tv-btc-long-close"
}
```

Set `reduce_only` to `true` if you only want to close an existing position. Remove the flag if you intend to reverse into a short position.

## Limit order to open a short

```json
{
  "secret": "<your-shared-secret>",
  "symbol": "ETHUSDT",
  "action": "SHORT_OPEN",
  "order_type": "LIMIT",
  "price": "{{close}}",
  "tif": "GTC",
  "margin": "50",
  "lev": "10",
  "alert_id": "tv-eth-short-open"
}
```

- `price`: Any TradingView variable or fixed price.
- `tif`: Time in force (`GTC`, `IOC`, or `FOK`).
- `margin`: One-off USDT margin budget for the order.
- `lev`: One-off leverage override for quantity calculation.

## Limit order to take profit on a short

```json
{
  "secret": "<your-shared-secret>",
  "symbol": "ETHUSDT",
  "action": "SHORT_CLOSE",
  "order_type": "LIMIT",
  "price": "{{strategy.order.contracts_exit}}",
  "qty": "{{strategy.position_size}}",
  "reduce_only": true,
  "tif": "IOC",
  "alert_id": "tv-eth-short-close"
}
```

- `qty`: Alias for `quantity`; useful when reusing strategy variables.
- `reduce_only`: Ensures the order only decreases exposure.

## Mapping TradingView strategy variables

TradingView replaces expressions such as `{{strategy.order.contracts}}`, `{{strategy.position_size}}`, or `{{close}}` with runtime values before sending the webhook. Combine them with the JSON keys described in the README so the bot can derive quantities, margins, and limit prices accurately.

For the full list of supported fields and aliases, see [README.md](../README.md#tradingview-alert-payload-format).
