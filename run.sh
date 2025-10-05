#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  cat <<'MSG'
[run.sh] Keine .env gefunden.
Bitte kopiere .env.example nach .env und trage deine Secrets ein:

  cp .env.example .env

Anschließend Skript erneut ausführen.
MSG
  exit 1
fi

VENV_DIR="${ROOT_DIR}/backend/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[run.sh] Erstelle virtuelles Python-Environment unter backend/.venv"
  python3 -m venv "${VENV_DIR}"
fi

export VIRTUAL_ENV="${VENV_DIR}"
export PATH="${VENV_DIR}/bin:${PATH}"

# Stelle sicher, dass pip aktuell ist und Abhängigkeiten installiert werden.
(
  cd "${ROOT_DIR}/backend"
  echo "[run.sh] Installiere/aktualisiere Abhängigkeiten"
  "${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
  "${VENV_DIR}/bin/pip" install -e ".[dev]"
)

PORT="${PORT:-8000}"
cd "${ROOT_DIR}/backend"

echo "[run.sh] Starte Backend unter http://0.0.0.0:${PORT}"
exec "${VENV_DIR}/bin/uvicorn" backend.app.main:app --host 0.0.0.0 --port "${PORT}" --reload
