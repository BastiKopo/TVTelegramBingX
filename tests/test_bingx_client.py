"""Tests for the BingX API client helpers."""

import asyncio

import pytest

from integrations.bingx_client import BingXClient, BingXClientError


def test_request_with_fallback_retries_missing_endpoints(monkeypatch) -> None:
    """If BingX removes an endpoint version the client should try the next one."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        if len(attempts) == 1:
            raise BingXClientError("BingX API error 100400: this api is not exist")
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        result = await client.get_margin_summary()
        assert result == {"ok": True}

    asyncio.run(runner())

    assert attempts == [
        "/openApi/swap/v3/user/margin",
        "/openApi/swap/v2/user/margin",
    ]


def test_request_with_fallback_tries_alternate_endpoint(monkeypatch) -> None:
    """If all versions of the primary path are missing, fall back to alternates."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        if "getMargin" in path:
            return {"ok": True}
        raise BingXClientError("BingX API error 100400: this api is not exist")

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        result = await client.get_margin_summary()
        assert result == {"ok": True}

    asyncio.run(runner())

    assert attempts == [
        "/openApi/swap/v3/user/margin",
        "/openApi/swap/v2/user/margin",
        "/openApi/swap/v1/user/margin",
        "/openApi/swap/v3/user/getMargin",
    ]


def test_request_with_fallback_propagates_other_errors(monkeypatch) -> None:
    """Errors other than missing endpoints should bubble up immediately."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        raise BingXClientError("BingX API error 200001: invalid signature")

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        with pytest.raises(BingXClientError):
            await client.get_margin_summary()

    asyncio.run(runner())

    assert attempts == ["/openApi/swap/v3/user/margin"]
