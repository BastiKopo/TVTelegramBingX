"""Tests for the webhook FastAPI application."""

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

