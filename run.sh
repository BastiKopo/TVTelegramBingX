#!/usr/bin/env bash
set -euo pipefail

printf '\n=== Starting TVTelegramBingX bot ===\n'

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

should_start_webhook() {
  case "${TRADINGVIEW_WEBHOOK_ENABLED:-}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if should_start_webhook; then
  if ! command -v uvicorn >/dev/null 2>&1; then
    echo "Error: uvicorn is required when TRADINGVIEW_WEBHOOK_ENABLED is true. Install it before running ./run.sh." >&2
    exit 1
  fi
fi

python -m tvtelegrambingx.main
