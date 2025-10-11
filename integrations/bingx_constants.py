"""Canonical BingX REST endpoint constants used by the integrations package."""

from __future__ import annotations

import os


# NOTE: The BingX Futures REST API is hosted exclusively under this base URL.
# Any deviation (alternate hostnames, additional prefixes, etc.) results in
# error 100400 ("this api is not exist") being returned by BingX.  The
# application therefore enforces this value at runtime to surface
# misconfiguration immediately.
BINGX_BASE = os.getenv("BINGX_BASE", "https://open-api.bingx.com").rstrip("/")

# Swap (Futures) V2 REST endpoints – documented by BingX and used for all
# trading operations performed by the bot.
PATH_ORDER = "/openApi/swap/v2/trade/order"
PATH_SET_LEVERAGE = "/openApi/swap/v2/trade/setLeverage"
PATH_SET_MARGIN = "/openApi/swap/v2/trade/setMarginMode"

# Public quote endpoints exposing market data.
PATH_QUOTE_PRICE = "/openApi/swap/v2/quote/price"
PATH_QUOTE_PREMIUM = "/openApi/swap/v2/quote/premiumIndex"
PATH_QUOTE_CONTRACTS = "/openApi/swap/v2/quote/contracts"

# Account endpoints require signed GET requests.
PATH_USER_BALANCE = "/openApi/swap/v2/user/balance"
PATH_USER_POSITIONS = "/openApi/swap/v2/user/positions"
PATH_USER_OPEN_ORDERS = "/openApi/swap/v2/user/openOrders"


__all__ = [
    "BINGX_BASE",
    "PATH_ORDER",
    "PATH_SET_LEVERAGE",
    "PATH_SET_MARGIN",
    "PATH_QUOTE_PRICE",
    "PATH_QUOTE_PREMIUM",
    "PATH_QUOTE_CONTRACTS",
    "PATH_USER_BALANCE",
    "PATH_USER_POSITIONS",
    "PATH_USER_OPEN_ORDERS",
]
