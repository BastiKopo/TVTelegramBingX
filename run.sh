#!/usr/bin/env bash
set -euo pipefail

printf '\n=== Starting TVTelegramBingX bot ===\n'

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

cleanup() {
  if [ -n "${WEBHOOK_PID:-}" ]; then
    printf '\nStopping webhook server (PID %s)\n' "$WEBHOOK_PID"
    kill "$WEBHOOK_PID" >/dev/null 2>&1 || true
    wait "$WEBHOOK_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

is_enabled() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if is_enabled "${TRADINGVIEW_WEBHOOK_ENABLED:-}"; then
  : "${TRADINGVIEW_WEBHOOK_SECRET:?TRADINGVIEW_WEBHOOK_SECRET must be set when the webhook is enabled}" 
  : "${TLS_CERT_PATH:?TLS_CERT_PATH must be set when the webhook is enabled}" 
  : "${TLS_KEY_PATH:?TLS_KEY_PATH must be set when the webhook is enabled}" 

  WEBHOOK_HOST=${TRADINGVIEW_WEBHOOK_HOST:-0.0.0.0}
  WEBHOOK_PORT=${TRADINGVIEW_WEBHOOK_PORT:-8443}

  printf '\n=== Starting TradingView webhook (https://%s:%s/tradingview-webhook) ===\n' "$WEBHOOK_HOST" "$WEBHOOK_PORT"
  uvicorn --factory webhook.server:create_app \
    --host "$WEBHOOK_HOST" \
    --port "$WEBHOOK_PORT" \
    --ssl-certfile "$TLS_CERT_PATH" \
    --ssl-keyfile "$TLS_KEY_PATH" &
  WEBHOOK_PID=$!
  sleep 1
fi

python -m bot.telegram_bot

if [ -n "${WEBHOOK_PID:-}" ]; then
  wait "$WEBHOOK_PID" 2>/dev/null || true
fi
