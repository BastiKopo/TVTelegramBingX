#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

ensure_python_version() {
  local candidate="$1"

  if ! command -v "${candidate}" >/dev/null 2>&1; then
    return 1
  fi

  "${candidate}" -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

if ensure_python_version python3; then
  PYTHON_BIN="python3"
elif ensure_python_version python3.11; then
  PYTHON_BIN="python3.11"
else
  cat <<'MSG'
[run.sh] Konnte keinen Python-Interpreter >= 3.11 finden.
Bitte installiere Python 3.11 (oder neuer) und stelle sicher, dass python3 oder python3.11 im PATH verfügbar ist.
MSG
  exit 1
fi

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
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

export VIRTUAL_ENV="${VENV_DIR}"
export PATH="${VENV_DIR}/bin:${PATH}"

PYTHON_BIN="${VENV_DIR}/bin/python"

# Stelle sicher, dass pip aktuell ist und Abhängigkeiten installiert werden.
(
  cd "${ROOT_DIR}/backend"
  echo "[run.sh] Installiere/aktualisiere Abhängigkeiten"
  "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null
  "${PYTHON_BIN}" -m pip install -e ".[dev]"
)

PORT="${PORT:-8000}"
cd "${ROOT_DIR}/backend"

echo "[run.sh] Starte Backend unter http://0.0.0.0:${PORT}"
exec "${VENV_DIR}/bin/uvicorn" backend.app.main:app --host 0.0.0.0 --port "${PORT}" --reload
