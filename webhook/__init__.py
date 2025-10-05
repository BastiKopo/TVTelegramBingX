"""Webhook integration package for TradingView alerts."""

from .server import create_app

__all__ = ["create_app"]
