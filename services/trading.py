"""Shared trading helpers used by manual and automated execution flows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class _SymbolSyncState:
    """Cached exchange configuration for a traded symbol."""

    margin_mode: str | None
    margin_coin: str | None
    lev_long: int
    lev_short: int
    hedge_mode: bool


_SYNCED_SYMBOL_SETTINGS: dict[str, _SymbolSyncState] = {}


def invalidate_symbol_configuration(symbol: str | None = None) -> None:
    """Remove cached configuration for *symbol*.

    When *symbol* is ``None`` the cache is cleared entirely.  The helper is used
    by the Telegram commands to ensure that manual adjustments are synchronised
    with BingX before the next order for the affected symbols is submitted.
    """

    if symbol is None:
        _SYNCED_SYMBOL_SETTINGS.clear()
        return

    token = symbol.strip().upper()
    if token:
        _SYNCED_SYMBOL_SETTINGS.pop(token, None)

from bot.state import BotState
from integrations.bingx_client import BingXClient, BingXClientError
from services.sizing import qty_from_margin_usdt

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExecutedOrder:
    """Container holding the prepared order payload and API response."""

    payload: Mapping[str, Any]
    response: Any
    quantity: float
    price: float
    leverage: float


async def execute_market_order(
    client: BingXClient,
    *,
    state: BotState,
    symbol: str,
    side: str,
    quantity: float | None = None,
    margin_usdt: float | None = None,
    leverage: float | None = None,
    margin_mode: str | None = None,
    margin_coin: str | None = None,
    position_side: str | None = None,
    reduce_only: bool = False,
    client_order_id: str | None = None,
    order_type: str = "MARKET",
    price: float | None = None,
    time_in_force: str | None = None,
    symbol_meta: Mapping[str, Mapping[str, str]] | None = None,
    dry_run: bool = False,
) -> ExecutedOrder:
    """Execute a futures market order using the shared configuration from *state*.

    The helper synchronises position mode, margin type and leverage before
    submitting the order to guarantee that manual and automated trades share the
    exact same execution path.
    """

    cfg = state.global_trade
    symbol_token = symbol.strip().upper()
    if not symbol_token:
        raise BingXClientError("Kein Handelssymbol angegeben.")
    side_token = side.strip().upper()
    if side_token not in {"BUY", "SELL"}:
        raise BingXClientError(f"Unsupported order side: {side}")

    order_type_token = str(order_type).strip().upper() or "MARKET"
    if order_type_token not in {"MARKET", "LIMIT"}:
        raise BingXClientError(f"Unsupported order type: {order_type}")

    tif_token: str | None
    limit_price: float | None
    if order_type_token == "LIMIT":
        try:
            limit_price = float(price) if price is not None else None
        except (TypeError, ValueError):
            limit_price = None
        if limit_price is None or limit_price <= 0:
            raise BingXClientError("Limit-Orders benötigen einen positiven Preis.")

        tif_candidate = str(time_in_force or "GTC").strip().upper() or "GTC"
        tif_token = tif_candidate if tif_candidate in {"GTC", "IOC", "FOK"} else "GTC"
    else:
        limit_price = None
        tif_token = None

    margin_mode_value = margin_mode or ("ISOLATED" if cfg.isolated else "CROSSED")
    if isinstance(margin_mode_value, str):
        margin_mode_value = margin_mode_value.strip().upper() or (
            "ISOLATED" if cfg.isolated else "CROSSED"
        )

    margin_coin_value = margin_coin or state.normalised_margin_asset()
    if isinstance(margin_coin_value, str):
        margin_coin_value = margin_coin_value.strip().upper() or state.normalised_margin_asset()

    lev_long = max(1, int(cfg.lev_long or 1))
    lev_short = max(1, int(cfg.lev_short or lev_long))

    leverage_override_value: int | None = None
    if leverage is not None:
        try:
            leverage_override_value = max(1, int(float(leverage)))
        except (TypeError, ValueError):
            leverage_override_value = None

    if leverage_override_value is not None:
        lev_long = leverage_override_value
        lev_short = leverage_override_value

    leverage_for_side = lev_long if side_token == "BUY" else lev_short

    target_hedge_mode = bool(cfg.hedge_mode)
    effective_hedge_mode = target_hedge_mode
    remote_hedge_mode: bool | None = None

    try:
        remote_hedge_mode = await client.get_position_mode()
    except BingXClientError as exc:
        LOGGER.warning(
            "Positionsmodus konnte nicht abgefragt werden für %s: %s",
            symbol_token,
            exc,
        )
    else:
        effective_hedge_mode = remote_hedge_mode

    if remote_hedge_mode is None or remote_hedge_mode != target_hedge_mode:
        try:
            await client.set_position_mode(target_hedge_mode)
            effective_hedge_mode = target_hedge_mode
        except BingXClientError as exc:
            LOGGER.warning("Failed to update position mode for %s: %s", symbol_token, exc)
            if remote_hedge_mode is not None:
                effective_hedge_mode = remote_hedge_mode

    if isinstance(position_side, str):
        token = position_side.strip().upper()
        position_side = token if token in {"LONG", "SHORT"} else None

    if position_side is None and effective_hedge_mode:
        position_side = "LONG" if side_token == "BUY" else "SHORT"
    elif not effective_hedge_mode and position_side is not None:
        LOGGER.info(
            "PositionSide %s wird ignoriert, da Konto im One-Way-Modus handelt.",
            position_side,
        )
        position_side = None
    elif not effective_hedge_mode:
        position_side = None

    budget = margin_usdt if margin_usdt is not None else cfg.margin_usdt
    try:
        margin_budget = float(budget)
    except (TypeError, ValueError):
        margin_budget = cfg.margin_usdt

    if margin_budget <= 0 and quantity is None:
        raise BingXClientError(
            "Autotrade-Konfiguration enthält keinen gültigen Margin-Wert."
        )

    target_state = _SymbolSyncState(
        margin_mode=margin_mode_value,
        margin_coin=margin_coin_value,
        lev_long=lev_long,
        lev_short=lev_short,
        hedge_mode=bool(effective_hedge_mode),
    )

    cached_state = _SYNCED_SYMBOL_SETTINGS.get(symbol_token)
    margin_requires_sync = (
        cached_state is None
        or cached_state.margin_mode != target_state.margin_mode
        or cached_state.margin_coin != target_state.margin_coin
    )
    leverage_requires_sync = (
        cached_state is None
        or cached_state.lev_long != target_state.lev_long
        or cached_state.lev_short != target_state.lev_short
        or cached_state.hedge_mode != target_state.hedge_mode
        or cached_state.margin_coin != target_state.margin_coin
    )

    margin_synced = not margin_requires_sync
    leverage_synced = not leverage_requires_sync

    if margin_requires_sync:
        try:
            set_margin_mode = getattr(client, "set_margin_mode", None)
            if callable(set_margin_mode):
                await set_margin_mode(
                    symbol=symbol_token,
                    marginMode=str(margin_mode_value),
                    marginCoin=margin_coin_value,
                )
            else:
                legacy_set_margin = getattr(client, "set_margin_type", None)
                if not callable(legacy_set_margin):
                    raise BingXClientError(
                        "BingX client does not support margin configuration APIs."
                    )
                await legacy_set_margin(
                    symbol=symbol_token,
                    margin_mode=str(margin_mode_value),
                    margin_coin=margin_coin_value,
                )
        except BingXClientError as exc:
            LOGGER.warning(
                "Failed to synchronise margin configuration for %s: %s",
                symbol_token,
                exc,
            )
        else:
            margin_synced = True

    if leverage_requires_sync:
        try:
            await client.set_leverage(
                symbol=symbol_token,
                lev_long=lev_long,
                lev_short=lev_short,
                hedge=effective_hedge_mode,
                margin_coin=margin_coin_value,
            )
        except BingXClientError as exc:
            LOGGER.warning("Failed to synchronise leverage for %s: %s", symbol_token, exc)
        else:
            leverage_synced = True

    if margin_synced and leverage_synced:
        _SYNCED_SYMBOL_SETTINGS[symbol_token] = target_state
    else:
        _SYNCED_SYMBOL_SETTINGS.pop(symbol_token, None)

    mark_price = await client.get_mark_price(symbol_token)
    filters = await client.get_symbol_filters(symbol_token)
    step_size = float(filters.get("step_size", 0.0))
    min_qty = float(filters.get("min_qty", 0.0))
    min_notional_raw = filters.get("min_notional")
    min_notional = float(min_notional_raw) if min_notional_raw is not None else None

    meta_entry = symbol_meta.get(symbol_token) if symbol_meta else None
    if step_size <= 0 and meta_entry:
        step_candidate = meta_entry.get("stepSize") or meta_entry.get("step_size")
        try:
            step_size = float(step_candidate)
        except (TypeError, ValueError):
            step_size = step_size

    if min_qty <= 0 and meta_entry:
        min_candidate = meta_entry.get("minQty") or meta_entry.get("min_qty")
        try:
            min_qty = float(min_candidate)
        except (TypeError, ValueError):
            pass

    if min_notional is None and meta_entry:
        notional_candidate = meta_entry.get("minNotional") or meta_entry.get("min_notional")
        try:
            min_notional = float(notional_candidate) if notional_candidate is not None else None
        except (TypeError, ValueError):
            min_notional = min_notional

    if step_size <= 0:
        raise BingXClientError(
            f"BingX lieferte keinen gültigen step_size-Filter für {symbol_token}"
        )

    qty_text_value: str | None = None

    if quantity is None:
        try:
            sizing_price = limit_price if limit_price is not None else mark_price
            step_token = Decimal(str(step_size))
            step_text = format(step_token.normalize(), "f")
            if "." in step_text:
                step_text = step_text.rstrip("0").rstrip(".")
            min_qty_text = None
            if min_qty > 0:
                min_qty_dec = Decimal(str(min_qty)).normalize()
                min_qty_text = format(min_qty_dec, "f").rstrip("0").rstrip(".")
            min_notional_text = None
            if min_notional is not None and min_notional > 0:
                min_notional_dec = Decimal(str(min_notional)).normalize()
                min_notional_text = (
                    format(min_notional_dec, "f").rstrip("0").rstrip(".")
                )

            qty_text = qty_from_margin_usdt(
                str(margin_budget),
                int(leverage_for_side),
                str(sizing_price),
                step_text,
                min_qty=min_qty_text,
                min_notional=min_notional_text,
            )
            qty_text_value = qty_text
            order_quantity = float(Decimal(qty_text))
        except ValueError as exc:
            raise BingXClientError(
                f"Ordergröße konnte aus Margin nicht berechnet werden: {exc}"
            ) from exc
    else:
        order_quantity = float(quantity)
        if order_quantity <= 0:
            raise BingXClientError("Positionsgröße muss größer als 0 sein.")

    payload: dict[str, Any] = {
        "symbol": symbol_token,
        "side": side_token,
        "quantity": order_quantity,
        "order_type": order_type_token,
        "leverage": leverage_for_side,
        "margin_mode": margin_mode_value,
        "margin_coin": margin_coin_value,
        "margin_usdt": float(max(margin_budget, 0.0)),
        "position_side": position_side,
        "hedge_mode": effective_hedge_mode,
        "reduce_only": reduce_only,
        "mark_price": mark_price,
    }

    if limit_price is not None:
        payload["price"] = limit_price
        if tif_token is not None:
            payload["time_in_force"] = tif_token
        payload["mark_price"] = mark_price
    else:
        payload["price"] = mark_price
    if client_order_id:
        payload["client_order_id"] = client_order_id

    order_calls = getattr(client, "order_calls", None)
    if isinstance(order_calls, list):
        order_calls.append(dict(payload))

    if dry_run:
        LOGGER.info("DRY_RUN aktiv – Order nicht gesendet: %s", payload)
        response: Any = {"status": "dry-run", "payload": dict(payload)}
    else:
        if qty_text_value is None:
            qty_text = format(order_quantity, "f").rstrip("0").rstrip(".") or "0"
        else:
            qty_text = qty_text_value
        position_arg = position_side or "BOTH"
        if order_type_token == "MARKET":
            market_method = getattr(client, "place_market", None)
            if callable(market_method):
                response = await market_method(
                    symbol=symbol_token,
                    side=side_token,
                    qty=qty_text,
                    positionSide=position_arg,
                    reduceOnly=reduce_only,
                    clientOrderId=client_order_id or "",
                )
            else:
                legacy_market = getattr(client, "place_futures_market_order", None)
                if not callable(legacy_market):
                    raise BingXClientError("BingX client does not support market orders.")
                response = await legacy_market(
                    symbol=symbol_token,
                    side=side_token,
                    qty=float(order_quantity),
                    position_side=position_side,
                    reduce_only=reduce_only,
                    client_order_id=client_order_id,
                )
        else:
            assert limit_price is not None
            price_text = format(limit_price, "f").rstrip("0").rstrip(".") or "0"
            limit_method = getattr(client, "place_limit", None)
            if callable(limit_method):
                response = await limit_method(
                    symbol=symbol_token,
                    side=side_token,
                    qty=qty_text,
                    price=price_text,
                    tif=tif_token or "GTC",
                    positionSide=position_arg,
                    reduceOnly=reduce_only,
                    clientOrderId=client_order_id or "",
                )
            else:
                legacy_order = getattr(client, "place_order", None)
                if not callable(legacy_order):
                    raise BingXClientError("BingX client does not support limit orders.")
                response = await legacy_order(
                    symbol=symbol_token,
                    side=side_token,
                    position_side=position_side,
                    quantity=order_quantity,
                    order_type="LIMIT",
                    price=limit_price,
                    margin_mode=str(margin_mode_value),
                    margin_coin=margin_coin_value,
                    leverage=float(leverage_for_side),
                    reduce_only=reduce_only,
                    client_order_id=client_order_id,
                )

    return ExecutedOrder(
        payload=payload,
        response=response,
        quantity=order_quantity,
        price=limit_price if limit_price is not None else mark_price,
        leverage=float(leverage_for_side),
    )
