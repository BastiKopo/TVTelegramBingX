"""Tests for the webhook FastAPI application."""

import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import Settings
from webhook.server import create_app


def make_settings(**overrides: Any) -> Settings:
    """Return Settings pre-populated with webhook configuration for tests."""

    base: dict[str, Any] = {
        "telegram_bot_token": "token",
        "bingx_api_key": "key",
        "bingx_api_secret": "secret",
        "tradingview_webhook_enabled": True,
        "tradingview_webhook_secret": "webhook-secret",
    }
    base.update(overrides)
    return Settings(**base)


def get_root_response(app: FastAPI) -> str:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def test_read_root_uses_app_docs_url() -> None:
    """The landing page should link to the configured docs URL when available."""

    app = create_app(make_settings())
    app.docs_url = "/custom-docs"

    page = get_root_response(app)

    assert "href=\"/custom-docs\"" in page
    assert "Documentation disabled" not in page


def test_read_root_handles_docs_disabled() -> None:
    """When documentation is disabled the page should avoid broken links."""

    app = create_app(make_settings())
    app.docs_url = None

    page = get_root_response(app)

    assert "Documentation disabled" in page
    assert "href=\"" not in page


def test_root_responds_with_html_content_type() -> None:
    """The landing page should be served as HTML so browsers render it."""

    app = create_app(make_settings())

    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    asyncio.run(app(scope, receive, send))

    assert messages, "ASGI application did not send any messages"
    start_message = messages[0]
    assert start_message["type"] == "http.response.start"

    headers = {key.decode(): value.decode() for key, value in start_message.get("headers", [])}
    assert headers.get("content-type") == "text/html; charset=utf-8"


def test_webhook_accepts_numeric_secret_in_payload() -> None:
    """Secrets provided without quotes should be converted to strings."""

    app = create_app(make_settings(tradingview_webhook_secret="123456789"))
    client = TestClient(app)

    response = client.post(
        "/tradingview-webhook",
        json={
            "secret": 123456789,
            "symbol": "LTCUSDT",
            "action": "long_open",
            "alert_id": "numeric-secret-test",
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_webhook_rejects_invalid_secret_with_401() -> None:
    """Webhook should return 401 for incorrect secrets."""

    app = create_app(make_settings(tradingview_webhook_secret="expected"))
    client = TestClient(app)

    response = client.post(
        "/tradingview-webhook",
        json={
            "secret": "wrong",  # Body secret mismatch
            "symbol": "BTCUSDT",
            "action": "long_open",
            "alert_id": "bad-secret",
        },
    )

    assert response.status_code == 401
    assert response.text == "invalid secret"


def test_webhook_accepts_secret_from_header() -> None:
    """Webhook should fall back to headers when the payload lacks a secret."""

    app = create_app(make_settings(tradingview_webhook_secret="header-secret"))
    client = TestClient(app)

    response = client.post(
        "/tradingview-webhook",
        headers={"X-TRADINGVIEW-SECRET": "header-secret"},
        json={
            "symbol": "ETHUSDT",
            "action": "long_open",
            "alert_id": "header-secret-test",
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_webhook_accepts_secrets_with_whitespace() -> None:
    """Secrets supplied with extra whitespace should be trimmed before comparison."""

    app = create_app(make_settings(tradingview_webhook_secret="expected"))
    client = TestClient(app)

    response = client.post(
        "/tradingview-webhook",
        json={
            "secret": "  expected  ",
            "symbol": "BTCUSDT",
            "action": "long_open",
            "alert_id": "trimmed-secret",
        },
    )

    assert response.status_code == 200
    assert response.text == "ok"


def test_webhook_health_endpoint_returns_ok_flag() -> None:
    """The webhook health endpoint should expose an ok flag."""

    app = create_app(make_settings())
    client = TestClient(app)

    response = client.get("/webhook/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_secret_hash_endpoint_masks_secret() -> None:
    """The secret hash endpoint should expose metadata without leaking the secret."""

    app = create_app(make_settings(tradingview_webhook_secret="super-secret"))
    client = TestClient(app)

    response = client.get("/webhook/secret-hash")

    assert response.status_code == 200
    payload = response.json()
    assert payload["present"] is True
    assert payload["len"] == len("super-secret")
    assert isinstance(payload["sha256_prefix"], str)
    assert payload["sha256_prefix"]

