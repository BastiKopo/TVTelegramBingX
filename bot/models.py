"""Pydantic models shared inside the bot package."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Sequence

from pydantic import BaseModel, Field


class BalanceSnapshot(BaseModel):
    """Lightweight view of a balance for bot consumption."""

    asset: str
    free: float
    locked: float
    total: float


class PnLSummary(BaseModel):
    """Aggregated PnL metrics exposed to the bot."""

    realized: float = 0.0
    unrealized: float = 0.0
    total: float = 0.0


class OpenPositionSnapshot(BaseModel):
    """Description of an open position the bot should render."""

    symbol: str
    action: str
    quantity: float
    entry_price: float
    leverage: int | None = None
    opened_at: datetime | None = None


class BotState(BaseModel):
    """Mirror of the backend bot state representation."""

    auto_trade_enabled: bool = False
    manual_confirmation_required: bool = True
    margin_mode: Literal["isolated", "cross"] = "isolated"
    leverage: int = Field(1, ge=1)
    updated_at: datetime | None = None
    balances: list[BalanceSnapshot] = Field(default_factory=list)
    pnl: PnLSummary = Field(default_factory=PnLSummary)
    open_positions: list[OpenPositionSnapshot] = Field(default_factory=list)


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


__all__ = [
    "BalanceSnapshot",
    "BotState",
    "OpenPositionSnapshot",
    "PnLSummary",
    "SignalRead",
    "SignalsReport",
]
