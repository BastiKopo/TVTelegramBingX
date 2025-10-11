"""FastAPI application exposing a TradingView webhook endpoint."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any, Mapping

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, Response

from config import Settings, get_settings
from webhook.dispatcher import publish_alert
from webhook.payloads import (
    DeduplicationCache,
    build_deduplication_key,
    safe_parse_tradingview,
)

LOGGER = logging.getLogger(__name__)

_SECRET_HEADER_CANDIDATES = (
    "X-Tradingview-Secret",
    "X-TRADINGVIEW-SECRET",
    "X-Webhook-Secret",
)

_DEDUP_CACHE = DeduplicationCache(ttl_seconds=30.0)
_DEDUP_LOCK = asyncio.Lock()


def _safe_equals(left: str, right: str) -> bool:
    """Compare two strings using a constant-time algorithm."""

    try:
        return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except Exception:
        return False


def _redact_preview(text: str, *candidates: str | None) -> str:
    """Return *text* truncated to 500 chars with sensitive tokens removed."""

    preview = text[:500]
    for candidate in candidates:
        if candidate:
            preview = preview.replace(candidate, "***")
    return preview


async def _read_raw_body(request: Request) -> bytes:
    """Return the raw request body without relying on ``Request.body`` being callable."""

    # FastAPI/Starlette normally expose ``body`` as an async method. Some middleware
    # (incorrectly) overwrites the attribute with the raw bytes, so we guard against
    # both cases.
    body_attr = getattr(request, "body", None)
    if callable(body_attr):
        try:
            raw = await body_attr()
        except TypeError:
            raw = None
        else:
            if isinstance(raw, (bytes, bytearray)):
                try:
                    request.state.raw_body = bytes(raw)
                except AttributeError:
                    pass
                return bytes(raw)
    else:
        if isinstance(body_attr, (bytes, bytearray)):
            raw = bytes(body_attr)
            try:
                request.state.raw_body = raw
            except AttributeError:
                pass
            return raw

    # Check whether a middleware cached the body on the ``state`` object.
    cached = getattr(getattr(request, "state", None), "raw_body", None)
    if isinstance(cached, (bytes, bytearray)):
        return bytes(cached)

    # Fallback to ``request.read`` if available.
    if hasattr(request, "read"):
        raw = await request.read()
        if isinstance(raw, (bytes, bytearray)):
            try:
                request.state.raw_body = bytes(raw)
            except AttributeError:
                pass
            return bytes(raw)

    raise RuntimeError("Unable to read request body")


def _extract_secret(request: Request, payload: Any) -> tuple[str | None, str]:
    """Return the shared secret from headers or payload along with its source."""

    for header_name in _SECRET_HEADER_CANDIDATES:
        value = request.headers.get(header_name)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned, f"header:{header_name.lower()}"
            if value:
                return value, f"header:{header_name.lower()}"

    if isinstance(payload, Mapping):
        secret_candidate = payload.get("secret") or payload.get("password")
        if isinstance(secret_candidate, str):
            cleaned = secret_candidate.strip()
            if cleaned:
                return cleaned, "body:string"
            if secret_candidate:
                return secret_candidate, "body:string"
        if isinstance(secret_candidate, (int, float)) and not isinstance(secret_candidate, bool):
            return str(secret_candidate), "body:numeric"

    return None, "none"


async def _dispatch_alert(payload: Mapping[str, Any]) -> None:
    """Enqueue *payload* unless it was processed recently."""

    dedup_key = build_deduplication_key(payload)
    if dedup_key:
        async with _DEDUP_LOCK:
            if _DEDUP_CACHE.seen(dedup_key):
                LOGGER.info(
                    "Duplicate TradingView alert ignored", extra={"dedup_key": dedup_key}
                )
                return

    await publish_alert(dict(payload))
    LOGGER.info("TradingView alert queued for Telegram processing")


async def _notify_parse_error(raw_body: str, reason: str) -> None:
    """Publish an informative alert explaining why parsing failed."""

    preview = raw_body[:500]
    message = f"⚠️ TradingView-Webhook konnte nicht verarbeitet werden: {reason}"
    alert_payload = {
        "message": message,
        "raw_payload_preview": preview,
        "_skip_autotrade": True,
    }
    await publish_alert(alert_payload)
    LOGGER.warning(
        "TradingView payload rejected", extra={"reason": reason, "preview": preview}
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a FastAPI application wired to the alert dispatcher."""

    settings = settings or get_settings()
    if not settings.tradingview_webhook_enabled:
        raise RuntimeError(
            "TradingView webhook is disabled. Set TRADINGVIEW_WEBHOOK_ENABLED=true to enable it."
        )

    secret = (settings.tradingview_webhook_secret or "").strip()
    if not secret:
        raise RuntimeError("TradingView webhook secret is not configured.")

    app = FastAPI(title="TVTelegramBingX TradingView Webhook")

    LOGGER.info(
        "TradingView webhook initialised",
        extra={"secret_configured": bool(secret)},
    )

    @app.get("/", response_class=HTMLResponse)
    async def read_root() -> str:
        doc_url = app.docs_url
        openapi_url = getattr(app, "openapi_url", None)

        actions = ""
        if doc_url:
            doc_button = (
                f'      <a class="button" href="{doc_url}" target="_blank" rel="noreferrer">Interaktive Docs öffnen</a>\n'
            )
            schema_button = (
                f'      <a class="button secondary" href="{openapi_url}" target="_blank" rel="noreferrer">OpenAPI Schema</a>\n'
                if openapi_url
                else ""
            )
            actions = "    <div class=\"actions\">\n" + doc_button + schema_button + "    </div>\n"
        else:
            actions = "    <p class=\"hint\">Documentation disabled</p>\n"

        version_label = app.version or "unbekannt"
        return (
            "<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "  <head>\n"
            "    <meta charset=\"utf-8\" />\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
            "    <title>TradingView Webhook Service</title>\n"
            "    <style>\n"
            "      :root{color-scheme:light dark;}*{box-sizing:border-box;}body{margin:0;font-family:'Inter',-apple-system,'Segoe UI',sans-serif;background:linear-gradient(135deg,#1f2937,#0f172a);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2.5rem;}\n"
            "      .card{background:rgba(15,23,42,0.85);border-radius:18px;box-shadow:0 24px 60px rgba(15,23,42,0.35);max-width:560px;width:100%;padding:2.5rem;color:#f8fafc;backdrop-filter:blur(14px);}\n"
            "      h1{margin:0 0 0.5rem;font-size:2rem;letter-spacing:-0.015em;}p.subtitle{margin:0 0 1.75rem;color:#cbd5f5;font-size:1rem;}ul{list-style:none;padding:0;margin:0 0 1.5rem;display:grid;gap:0.75rem;}\n"
            "      li{display:flex;flex-direction:column;gap:0.15rem;padding:0.65rem 0.85rem;border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(148,163,184,0.2);}li span.label{text-transform:uppercase;font-size:0.7rem;letter-spacing:0.12em;color:#94a3b8;}li span.value{font-size:1rem;font-weight:600;color:#e2e8f0;}\n"
            "      .actions{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem;}a.button{text-decoration:none;padding:0.75rem 1.25rem;border-radius:999px;font-weight:600;transition:transform 0.2s ease,box-shadow 0.2s ease;}a.button{background:#38bdf8;color:#0f172a;}a.button.secondary{background:transparent;color:#e2e8f0;border:1px solid rgba(148,163,184,0.4);}a.button:hover{transform:translateY(-1px);box-shadow:0 10px 25px rgba(56,189,248,0.35);}p.hint{margin:0 0 1.5rem;color:#94a3b8;font-size:0.85rem;}footer{margin-top:2rem;font-size:0.75rem;color:#94a3b8;}\n"
            "      code{background:rgba(148,163,184,0.18);padding:0.15rem 0.4rem;border-radius:8px;font-size:0.85rem;}@media(max-width:600px){body{padding:1.5rem;}.card{padding:1.75rem;}}\n"
            "    </style>\n"
            "  </head>\n"
            "  <body>\n"
            "    <div class=\"card\">\n"
            f"      <h1>{app.title}</h1>\n"
            "      <p class=\"subtitle\">Bereit, TradingView Signale zu empfangen und an Telegram/BingX weiterzuleiten.</p>\n"
            "      <ul>\n"
            "        <li><span class=\"label\">Status</span><span class=\"value\">Online</span></li>\n"
            f"        <li><span class=\"label\">Service</span><span class=\"value\">{app.title}</span></li>\n"
            f"        <li><span class=\"label\">Version</span><span class=\"value\">{version_label}</span></li>\n"
            "        <li><span class=\"label\">Webhook Endpoint</span><span class=\"value\"><code>POST /tradingview-webhook</code></span></li>\n"
            "      </ul>\n"
            f"{actions}"
            "      <footer>Nutze die konfigurierte Secret-Übereinstimmung, um deine TradingView Alerts sicher zu halten.</footer>\n"
            "    </div>\n"
            "  </body>\n"
            "</html>\n"
        )

    @app.get("/webhook/health")
    async def webhook_health() -> Mapping[str, bool]:
        return {"ok": True}

    @app.get("/webhook/secret-hash")
    async def webhook_secret_hash() -> Mapping[str, object]:
        import hashlib

        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest() if secret else ""
        return {
            "present": bool(secret),
            "length": len(secret),
            "sha256_prefix": digest[:12] if digest else "",
        }

    @app.post("/tradingview-webhook")
    async def tradingview_webhook(request: Request) -> Response | Mapping[str, str]:
        try:
            raw_body_bytes = await _read_raw_body(request)
        except Exception:
            LOGGER.exception("Failed to read TradingView webhook body")
            return {"status": "ignored", "reason": "body_unreadable"}
        raw_body = raw_body_bytes.decode("utf-8", "replace")

        try:
            payload_for_secret = json.loads(raw_body)
        except json.JSONDecodeError:
            payload_for_secret = None

        provided_secret, secret_source = _extract_secret(request, payload_for_secret)

        LOGGER.info(
            "TradingView webhook request received",
            extra={
                "ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                "content_type": request.headers.get("content-type"),
                "length": len(raw_body_bytes),
                "preview": _redact_preview(raw_body, secret, provided_secret),
                "secret_source": secret_source,
                "secret_provided": bool(provided_secret),
                "secret_configured": bool(secret),
            },
        )

        if not provided_secret:
            LOGGER.warning(
                "Rejected webhook call due to invalid secret",
                extra={
                    "secret_source": secret_source,
                    "secret_reason": "missing",
                },
            )
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content="invalid secret",
            )

        if not _safe_equals(secret, str(provided_secret)):
            LOGGER.warning(
                "Rejected webhook call due to invalid secret",
                extra={
                    "secret_source": secret_source,
                    "secret_reason": "mismatch",
                    "provided_length": len(provided_secret),
                    "expected_length": len(secret),
                },
            )
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content="invalid secret",
            )

        try:
            payload = safe_parse_tradingview(raw_body)
        except ValueError as exc:
            asyncio.create_task(_notify_parse_error(raw_body, str(exc)))
            return {"status": "ignored", "reason": "invalid_payload"}

        LOGGER.info(
            "TradingView webhook accepted",
            extra={
                "symbol": payload.get("symbol"),
                "action": payload.get("action"),
                "alert_id": payload.get("alert_id"),
                "secret_source": secret_source,
            },
        )

        asyncio.create_task(_dispatch_alert(payload))
        return Response(status_code=status.HTTP_200_OK, content="ok")

    return app


__all__ = ["create_app"]

