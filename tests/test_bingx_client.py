"""Tests for the BingX API client helpers."""

import asyncio
from typing import Any

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


def test_set_margin_type_uses_margin_coin(monkeypatch) -> None:
    """Setting the margin type forwards symbol, mode and coin to BingX."""

    client = BingXClient(api_key="key", api_secret="secret")
    captured: dict[str, Any] = {}

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        captured["method"] = method
        captured["paths"] = paths
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    asyncio.run(
        client.set_margin_type(symbol="BTCUSDT", margin_mode="ISOLATED", margin_coin="USDT"),
    )

    assert captured["method"] == "POST"
    assert captured["paths"][0] == "/openApi/swap/v3/user/marginType"
    assert captured["params"]["symbol"] == "BTC-USDT"
    assert captured["params"]["marginType"] == "ISOLATED"
    assert captured["params"]["marginCoin"] == "USDT"


def test_set_leverage_forwards_optional_arguments(monkeypatch) -> None:
    """Leverage updates include margin context when provided."""

    client = BingXClient(api_key="key", api_secret="secret")
    captured: dict[str, Any] = {}

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        captured["method"] = method
        captured["paths"] = paths
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    asyncio.run(
        client.set_leverage(
            symbol="ETHUSDT",
            leverage=7.5,
            margin_mode="ISOLATED",
            margin_coin="USDT",
        ),
    )

    assert captured["method"] == "POST"
    assert captured["paths"][0] == "/openApi/swap/v3/user/leverage"
    assert captured["params"]["symbol"] == "ETH-USDT"
    assert captured["params"]["leverage"] == 7.5
    assert captured["params"]["marginType"] == "ISOLATED"
    assert captured["params"]["marginCoin"] == "USDT"


def test_symbol_normalisation_handles_common_formats() -> None:
    """Symbols are coerced into BingX' futures notation."""

    client = BingXClient(api_key="key", api_secret="secret")

    assert client._normalise_symbol("btcusdt") == "BTC-USDT"
    assert client._normalise_symbol("BINANCE:ethusdt") == "ETH-USDT"
    assert client._normalise_symbol("xrp/usdt") == "XRP-USDT"
    assert client._normalise_symbol("ada_usdc") == "ADA-USDC"


def test_sign_parameters_encodes_and_signs_complex_values(monkeypatch) -> None:
    """Special characters are percent encoded before signature creation."""

    client = BingXClient(api_key="key", api_secret="secret")

    monkeypatch.setattr(
        "integrations.bingx_client.time.time", lambda: 1700000000.123
    )

    query_string = client._sign_parameters(
        {
            "symbol": "LTC-USDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": 1.25,
            "clientOrderId": "tv:abc def",
            "reduceOnly": True,
        }
    )

    assert (
        query_string
        == "clientOrderId=tv%3Aabc%20def&quantity=1.25&reduceOnly=true&side=BUY&"
        "symbol=LTC-USDT&timestamp=1700000000123&type=MARKET&signature="
        "76ade777efe4a05053c867fe4131737b4ae6b328522cf6c670cc332013719308"
    )
