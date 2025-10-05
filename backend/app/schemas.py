"""Pydantic and SQLModel schemas used across the backend."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import JSON, String, UniqueConstraint
from sqlmodel import Column, DateTime, Field as SQLField, Relationship, SQLModel


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
    orders: list["Order"] = Relationship(back_populates="signal")


class SignalRead(BaseModel):
    """Response schema exposed by the API."""

    id: int
    symbol: str
    action: TradeAction
    timestamp: datetime
    quantity: float

    class Config:
        from_attributes = True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """Represents a trading user interacting with the system."""

    __tablename__ = "users"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    username: str = SQLField(
        index=True, nullable=False, unique=True, sa_column=Column(String(64), nullable=False)
    )
    email: Optional[str] = SQLField(
        default=None, index=True, unique=True, sa_column=Column(String(255), nullable=True)
    )
    is_active: bool = SQLField(default=True, nullable=False)
    created_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    bot_sessions: list["BotSession"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    orders: list["Order"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    positions: list["Position"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    balances: list["Balance"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class BotSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class BotSession(SQLModel, table=True):
    """Tracks the lifecycle of automated trading bot sessions."""

    __tablename__ = "bot_sessions"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_bot_session_user_name"),)

    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(foreign_key="users.id", nullable=False, index=True)
    name: str = SQLField(sa_column=Column(String(128), nullable=False))
    status: BotSessionStatus = SQLField(default=BotSessionStatus.ACTIVE, nullable=False)
    started_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    ended_at: Optional[datetime] = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    context: dict | None = SQLField(default=None, sa_column=Column(JSON, nullable=True))

    user: User = Relationship(back_populates="bot_sessions")
    orders: list["Order"] = Relationship(
        back_populates="bot_session", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    positions: list["Position"] = Relationship(
        back_populates="bot_session", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(SQLModel, table=True):
    """Orders submitted to the exchange as a consequence of signals."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("exchange_order_id", name="uq_orders_exchange_order_id"),
    )

    id: Optional[int] = SQLField(default=None, primary_key=True)
    signal_id: int = SQLField(foreign_key="signals.id", nullable=False, index=True)
    user_id: int = SQLField(foreign_key="users.id", nullable=False, index=True)
    bot_session_id: int = SQLField(foreign_key="bot_sessions.id", nullable=False, index=True)
    symbol: str = SQLField(index=True, sa_column=Column(String(64), nullable=False))
    action: TradeAction = SQLField(nullable=False)
    status: OrderStatus = SQLField(default=OrderStatus.PENDING, nullable=False)
    quantity: float = SQLField(nullable=False)
    price: Optional[float] = SQLField(default=None)
    exchange_order_id: Optional[str] = SQLField(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    created_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    signal: Signal = Relationship(back_populates="orders")
    user: User = Relationship(back_populates="orders")
    bot_session: BotSession = Relationship(back_populates="orders")


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    LIQUIDATED = "liquidated"


class Position(SQLModel, table=True):
    """Tracks open positions for users and sessions."""

    __tablename__ = "positions"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(foreign_key="users.id", nullable=False, index=True)
    bot_session_id: Optional[int] = SQLField(foreign_key="bot_sessions.id", default=None, index=True)
    symbol: str = SQLField(index=True, sa_column=Column(String(64), nullable=False))
    action: TradeAction = SQLField(nullable=False)
    quantity: float = SQLField(nullable=False)
    entry_price: float = SQLField(nullable=False)
    leverage: Optional[int] = SQLField(default=None)
    status: PositionStatus = SQLField(default=PositionStatus.OPEN, nullable=False)
    opened_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    closed_at: Optional[datetime] = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    user: User = Relationship(back_populates="positions")
    bot_session: Optional[BotSession] = Relationship(back_populates="positions")


class Balance(SQLModel, table=True):
    """Represents available funds for a user per asset."""

    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("user_id", "asset", name="uq_balances_user_asset"),)

    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(foreign_key="users.id", nullable=False, index=True)
    asset: str = SQLField(sa_column=Column(String(32), nullable=False))
    free: float = SQLField(default=0.0, nullable=False)
    locked: float = SQLField(default=0.0, nullable=False)
    updated_at: datetime = SQLField(
        default_factory=_utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    user: User = Relationship(back_populates="balances")
