from __future__ import annotations

import importlib
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from backend.app import config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _dispatch_health_request(app, *, scheme: str = "http") -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/health",
        "raw_path": b"/health",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    await app(scope, receive, send)
    return messages


async def _exercise_health_endpoint(
    monkeypatch: pytest.MonkeyPatch, *, force_https: bool | None
) -> tuple[int, dict[str, str], bytes]:
    if force_https is True:
        monkeypatch.setenv("FORCE_HTTPS", "true")
    elif force_https is False:
        monkeypatch.setenv("FORCE_HTTPS", "false")
    else:
        monkeypatch.delenv("FORCE_HTTPS", raising=False)

    config.get_settings.cache_clear()
    import backend.app.main as main_module

    main_module = importlib.reload(main_module)
    monkeypatch.setattr(main_module, "init_engine", AsyncMock(return_value=None))

    await main_module.app.router.startup()
    try:
        messages = await _dispatch_health_request(main_module.app)
    finally:
        await main_module.app.router.shutdown()

    status_message = next(message for message in messages if message["type"] == "http.response.start")
    headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in status_message["headers"]}
    body = b"".join(message["body"] for message in messages if message["type"] == "http.response.body")

    monkeypatch.setenv("FORCE_HTTPS", "false")
    config.get_settings.cache_clear()
    importlib.reload(main_module)

    return status_message["status"], headers, body


@pytest.mark.anyio("asyncio")
async def test_healthcheck_allows_http_when_https_not_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    status_code, headers, body = await _exercise_health_endpoint(monkeypatch, force_https=None)
    assert status_code == status.HTTP_200_OK
    assert headers.get("location") is None
    assert json.loads(body.decode("utf-8")) == {"status": "ok"}


@pytest.mark.anyio("asyncio")
async def test_healthcheck_redirects_when_https_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    status_code, headers, _ = await _exercise_health_endpoint(monkeypatch, force_https=True)
    assert status_code == status.HTTP_307_TEMPORARY_REDIRECT
    assert headers.get("location", "").startswith("https://")
