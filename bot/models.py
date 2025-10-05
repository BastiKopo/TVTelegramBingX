"""Pydantic models shared inside the bot package."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field


class BotState(BaseModel):
    """Mirror of the backend bot state representation."""

    auto_trade_enabled: bool = False
    manual_confirmation_required: bool = True
    margin_mode: Literal["isolated", "cross"] = "isolated"
    leverage: int = Field(1, ge=1)
    updated_at: datetime | None = None


class SignalRead(BaseModel):
    """Subset of signal information used in bot reports."""

    id: int
    symbol: str
    action: str
    timestamp: datetime
    quantity: float


class SignalsReport(BaseModel):
    """Aggregated report payload for templating convenience."""

    items: Sequence[SignalRead]


__all__ = ["BotState", "SignalRead", "SignalsReport"]
