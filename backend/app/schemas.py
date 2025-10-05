"""Pydantic and SQLModel schemas used across the backend."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import JSON
from sqlmodel import Column, DateTime, Field as SQLField, SQLModel


class TradeAction(str, Enum):
    """Allowed trading actions emitted by TradingView."""

    BUY = "buy"
    SELL = "sell"


class TradingViewSignal(BaseModel):
    """Payload schema expected from the TradingView webhook."""

    symbol: str = Field(..., min_length=1, max_length=32)
    action: TradeAction
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime
    quantity: float = Field(..., gt=0)
    stop_loss: Optional[float] = Field(default=None, ge=0)
    take_profit: Optional[float] = Field(default=None, ge=0)
    leverage: Optional[int] = Field(default=None, ge=1)
    margin_mode: Optional[Literal["isolated", "cross"]] = Field(default=None)


class Signal(SQLModel, table=True):
    """Persisted representation of incoming signals."""

    __tablename__ = "signals"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    symbol: str = SQLField(index=True)
    action: TradeAction
    confidence: Optional[float] = None
    timestamp: datetime = SQLField(sa_column=Column(DateTime(timezone=True)))
    quantity: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    leverage: Optional[int] = None
    margin_mode: Optional[str] = SQLField(default=None, index=True)
    raw_payload: dict = SQLField(sa_column=Column(JSON, nullable=False))


class SignalRead(BaseModel):
    """Response schema exposed by the API."""

    id: int
    symbol: str
    action: TradeAction
    timestamp: datetime
    quantity: float

    class Config:
        from_attributes = True
