#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

ensure_python_version() {
  local candidate="$1"
  local python_path=""

  if [[ -x "${candidate}" ]]; then
    python_path="${candidate}"
  else
    python_path="$(command -v "${candidate}" 2>/dev/null || true)"
  fi

  if [[ -z "${python_path}" ]]; then
    return 1
  fi

  "${python_path}" -c 'import sys; exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

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
VENV_PYTHON="${VENV_DIR}/bin/python"

if [[ -d "${VENV_DIR}" ]] && ! ensure_python_version "${VENV_PYTHON}"; then
  echo "[run.sh] Entferne virtuelles Environment mit inkompatibler Python-Version (< 3.11)"
  rm -rf "${VENV_DIR}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
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

  echo "[run.sh] Erstelle virtuelles Python-Environment unter backend/.venv"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if ! ensure_python_version "${VENV_PYTHON}"; then
  cat <<'MSG'
[run.sh] Das virtuelle Environment verwendet eine inkompatible Python-Version (< 3.11).
Bitte stelle sicher, dass ein Python-Interpreter >= 3.11 verfügbar ist und führe das Skript erneut aus.
MSG
  exit 1
fi

PYTHON_BIN="${VENV_PYTHON}"

export VIRTUAL_ENV="${VENV_DIR}"
export PATH="${VENV_DIR}/bin:${PATH}"

# Stelle sicher, dass pip aktuell ist und Abhängigkeiten installiert werden.
(
  cd "${ROOT_DIR}/backend"
  echo "[run.sh] Installiere/aktualisiere Abhängigkeiten"
  "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null
  "${PYTHON_BIN}" -m pip install -e ".[dev]"
)

PORT="${PORT:-8000}"

UVICORN_SSL_CERTFILE="${UVICORN_SSL_CERTFILE:-}"
UVICORN_SSL_KEYFILE="${UVICORN_SSL_KEYFILE:-}"
UVICORN_SSL_CA_CERT="${UVICORN_SSL_CA_CERT:-}"

UVICORN_ARGS=(backend.app.main:app --host 0.0.0.0 --port "${PORT}" --reload)

PROTOCOL="http"
if [[ -n "${UVICORN_SSL_CERTFILE}" && -n "${UVICORN_SSL_KEYFILE}" ]]; then
  UVICORN_ARGS+=(--ssl-certfile "${UVICORN_SSL_CERTFILE}" --ssl-keyfile "${UVICORN_SSL_KEYFILE}")
  if [[ -n "${UVICORN_SSL_CA_CERT}" ]]; then
    UVICORN_ARGS+=(--ssl-ca-certs "${UVICORN_SSL_CA_CERT}")
  fi
  PROTOCOL="https"
fi

echo "[run.sh] Starte Backend unter ${PROTOCOL}://0.0.0.0:${PORT}"
exec "${VENV_DIR}/bin/uvicorn" "${UVICORN_ARGS[@]}"
