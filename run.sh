#!/usr/bin/env bash
set -euo pipefail

printf '\n=== Starting TVTelegramBingX bot ===\n'

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python -m bot.telegram_bot
