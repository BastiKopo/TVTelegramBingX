"""Service layer for Telegram bot interactions with backend state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, TYPE_CHECKING

from ..config import Settings
from ..repositories.balance_repository import BalanceRepository
from ..repositories.bot_session_repository import BotSessionRepository
from ..repositories.order_repository import OrderRepository
from ..repositories.position_repository import PositionRepository
from ..repositories.signal_repository import SignalRepository
from ..repositories.user_repository import UserRepository
from ..schemas import (
    BalanceSnapshot,
    BotSession,
    BotState,
    BotSettingsUpdate,
    OpenPositionSnapshot,
    PnLSummary,
    Signal,
    TradeAction,
)

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from .bingx_account_service import BingXAccountService


class BotControlService:
    """Expose bot-facing operations for status management and reporting."""

    def __init__(
        self,
        signal_repository: SignalRepository,
        user_repository: UserRepository,
        bot_session_repository: BotSessionRepository,
        balance_repository: BalanceRepository,
        position_repository: PositionRepository,
        settings: Settings,
        order_repository: "OrderRepository | None" = None,
        bingx_account: "BingXAccountService | None" = None,
    ) -> None:
        self._signals = signal_repository
        self._users = user_repository
        self._bot_sessions = bot_session_repository
        self._balances = balance_repository
        self._positions = position_repository
        self._orders = order_repository
        self._settings = settings
        self._bingx_account = bingx_account

    async def get_state(self) -> BotState:
        session = await self._ensure_session()
        return await self._build_state(session)

    async def update_state(self, update: BotSettingsUpdate) -> BotState:
        session = await self._ensure_session()
        current = self._context_to_state(session.context)
        data = current.model_dump()
        data.update(update.model_dump(exclude_unset=True))
        data["updated_at"] = datetime.now(timezone.utc)
        persisted = await self._bot_sessions.save_context(
            session,
            self._state_to_context(data.items()),
        )
        if self._bingx_account and (update.margin_mode is not None or update.leverage is not None):
            await self._sync_bingx_preferences(
                data.get("margin_mode"),
                data.get("leverage"),
            )
        return await self._build_state(persisted)

    async def recent_signals(self, limit: int = 5) -> Iterable[Signal]:
        """Return the most recent signals for reporting."""

        return await self._signals.list_recent(limit)

    async def _ensure_session(self):
        user = await self._users.get_or_create_by_username(self._settings.trading_default_username)
        return await self._bot_sessions.get_or_create_active_session(
            user.id, self._settings.trading_default_session
        )

    def _context_to_state(self, context: dict | None) -> BotState:
        data = context or {}
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except ValueError:
                updated_at = None
        elif not isinstance(updated_at, datetime):
            updated_at = None

        balances_payload = data.get("balances", [])
        balances = [BalanceSnapshot.model_validate(item) for item in balances_payload]

        pnl_payload = data.get("pnl") or {}
        pnl = PnLSummary.model_validate(pnl_payload)

        open_positions_payload = data.get("open_positions", [])
        open_positions = [
            OpenPositionSnapshot.model_validate(item) for item in open_positions_payload
        ]

        return BotState(
            auto_trade_enabled=bool(data.get("auto_trade_enabled", False)),
            manual_confirmation_required=bool(data.get("manual_confirmation_required", True)),
            margin_mode=str(data.get("margin_mode", self._settings.default_margin_mode)),
            leverage=int(data.get("leverage", self._settings.default_leverage)),
            updated_at=updated_at,
            balances=balances,
            pnl=pnl,
            open_positions=open_positions,
        )

    def _state_to_context(self, items: Iterable[tuple[str, object]]) -> dict:
        context: dict[str, object] = {}
        for key, value in items:
            if key == "updated_at" and isinstance(value, datetime):
                context[key] = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            else:
                context[key] = value
        return context

    async def _build_state(self, session: BotSession) -> BotState:
        base_state = self._context_to_state(session.context)
        metrics = await self._collect_metrics(session)
        state = base_state.model_copy(update=metrics)
        desired_context = self._state_to_context(state.model_dump().items())
        if session.context != desired_context:
            await self._bot_sessions.save_context(session, desired_context)
        return state

    async def _collect_metrics(self, session: BotSession) -> dict[str, object]:
        balances = await self._balances.list_for_user(session.user_id)
        balance_snapshots = [
            BalanceSnapshot(
                asset=balance.asset,
                free=balance.free,
                locked=balance.locked,
                total=balance.free + balance.locked,
            )
            for balance in balances
        ]

        positions = await self._positions.list_open_for_user(session.user_id)
        open_positions = [
            OpenPositionSnapshot(
                symbol=position.symbol,
                action=position.action.value,
                quantity=position.quantity,
                entry_price=position.entry_price,
                leverage=position.leverage,
                opened_at=position.opened_at,
            )
            for position in positions
        ]

        pnl = await self._calculate_pnl(session.id)

        return {
            "balances": balance_snapshots,
            "open_positions": open_positions,
            "pnl": pnl,
        }

    async def _calculate_pnl(self, session_id: int) -> PnLSummary:
        if self._orders is None:
            return PnLSummary()

        orders = await self._orders.list_filled_for_session(session_id)
        realized = 0.0
        for order in orders:
            if order.price is None:
                continue
            direction = 1.0 if order.action == TradeAction.SELL else -1.0
            realized += direction * order.price * order.quantity

        return PnLSummary(realized=realized, unrealized=0.0, total=realized)

    async def _sync_bingx_preferences(self, margin_mode: str | None, leverage: int | None) -> None:
        if not self._bingx_account:
            return
        symbols = {signal.symbol for signal in await self._signals.list_recent(25)}
        if not symbols:
            return
        await self._bingx_account.ensure_preferences(symbols, margin_mode, leverage)


__all__ = ["BotControlService"]
