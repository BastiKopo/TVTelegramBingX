"""Optional AI gatekeeper for TradingView signals."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.utils.actions import CLOSE_ACTIONS, OPEN_ACTIONS, canonical_action

LOGGER = logging.getLogger(__name__)
CONFIG = ConfigStore()
SETTINGS: Optional[Settings] = None


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    mode: str
    universe: list[str]
    min_win_rate: float
    store_path: Path


@dataclass(frozen=True)
class AIDecision:
    allowed_actions: list[str]
    blocked_actions: list[str]
    mode: str
    reason: str
    evaluated_actions: list[str]
    score: Optional[float] = None


class LearningStore:
    """Small JSON-backed store for AI feedback and signal logs."""

    def __init__(self, path: Path, *, max_signals: int = 500) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._max_signals = max_signals
        if not self._path.exists():
            self._write(self._default_payload())

    def _default_payload(self) -> Dict[str, Any]:
        return {
            "meta": {"version": 1, "updated": int(time.time())},
            "stats": {},
            "signals": [],
        }

    def _read(self) -> Dict[str, Any]:
        with self._lock:
            if not self._path.exists():
                data = self._default_payload()
                self._write(data)
                return data
            try:
                raw = self._path.read_text(encoding="utf-8")
            except OSError:
                return self._default_payload()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = self._default_payload()

            if not isinstance(data, dict):
                data = self._default_payload()
            data.setdefault("meta", {"version": 1})
            data.setdefault("stats", {})
            data.setdefault("signals", [])
            return data

    def _write(self, data: Dict[str, Any]) -> None:
        with self._lock:
            data.setdefault("meta", {})
            data["meta"]["updated"] = int(time.time())
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            self._path.write_text(serialized, encoding="utf-8")

    def _get_action_stats(self, data: Dict[str, Any], symbol: str, action: str) -> Dict[str, Any]:
        stats = data.setdefault("stats", {})
        symbol_key = symbol.upper()
        stats.setdefault(symbol_key, {})
        stats[symbol_key].setdefault(action, {"wins": 0, "losses": 0})
        return stats[symbol_key][action]

    def get_win_rate(self, symbol: str, action: str) -> Optional[float]:
        data = self._read()
        stats = data.get("stats", {}).get(symbol.upper(), {}).get(action)
        if not isinstance(stats, dict):
            return None
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        total = wins + losses
        if total == 0:
            return None
        return wins / total

    def record_feedback(self, symbol: str, action: str, outcome: str) -> float:
        data = self._read()
        stats = self._get_action_stats(data, symbol, action)
        if outcome == "win":
            stats["wins"] = int(stats.get("wins", 0)) + 1
        else:
            stats["losses"] = int(stats.get("losses", 0)) + 1
        self._write(data)
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        total = wins + losses
        return wins / total if total else 0.0

    def log_signal(
        self,
        symbol: str,
        actions: Iterable[str],
        decision: AIDecision,
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        data = self._read()
        entry = {
            "timestamp": int(time.time()),
            "symbol": symbol,
            "actions": list(actions),
            "allowed": decision.allowed_actions,
            "blocked": decision.blocked_actions,
            "mode": decision.mode,
            "reason": decision.reason,
            "score": decision.score,
        }
        if payload is not None:
            entry["payload"] = payload
        signals = data.setdefault("signals", [])
        if not isinstance(signals, list):
            signals = []
            data["signals"] = signals
        signals.append(entry)
        if len(signals) > self._max_signals:
            data["signals"] = signals[-self._max_signals :]
        self._write(data)

    def summary_for_symbol(self, symbol: str) -> Dict[str, Dict[str, int]]:
        data = self._read()
        stats = data.get("stats", {}).get(symbol.upper(), {})
        if not isinstance(stats, dict):
            return {}
        summary: Dict[str, Dict[str, int]] = {}
        for action, values in stats.items():
            if not isinstance(values, dict):
                continue
            summary[action] = {
                "wins": int(values.get("wins", 0)),
                "losses": int(values.get("losses", 0)),
            }
        return summary

    def recent_signals(self, *, limit: int = 50) -> list[Dict[str, Any]]:
        data = self._read()
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            return []
        if limit <= 0:
            return []
        return signals[-limit:]


_STORE: Optional[LearningStore] = None


def configure(settings: Settings) -> None:
    """Initialise shared settings for the AI gatekeeper."""
    global SETTINGS
    SETTINGS = settings


def _split_universe(raw_value: Optional[str]) -> list[str]:
    if not raw_value:
        return []
    universe: List[str] = []
    for part in raw_value.replace(";", ",").replace("|", ",").split(","):
        trimmed = part.strip()
        if trimmed:
            universe.append(trimmed.upper())
    return universe


def _load_config() -> AIConfig:
    if SETTINGS is None:
        raise RuntimeError("AI gatekeeper not configured")

    config_data = CONFIG.get().get("_global", {})
    enabled = config_data.get("ai_enabled")
    if enabled is None:
        enabled = SETTINGS.ai_enabled
    mode = config_data.get("ai_mode") or SETTINGS.ai_mode
    if mode is None:
        mode = "off"
    mode = str(mode).lower()
    universe = config_data.get("ai_universe")
    if not universe:
        universe = SETTINGS.ai_universe
    if isinstance(universe, str):
        universe_list = _split_universe(universe)
    else:
        universe_list = [str(item).upper() for item in universe or [] if str(item).strip()]
    min_win_rate = SETTINGS.ai_min_win_rate
    store_path = Path(SETTINGS.ai_store_path) if SETTINGS.ai_store_path else Path.home() / ".tvtelegrambingx_ai.json"

    return AIConfig(
        enabled=bool(enabled),
        mode=mode,
        universe=universe_list,
        min_win_rate=min_win_rate,
        store_path=store_path,
    )


def _get_store() -> LearningStore:
    global _STORE
    if _STORE is None:
        config = _load_config()
        _STORE = LearningStore(config.store_path)
    return _STORE


def ai_status_text(symbol: Optional[str] = None) -> str:
    config = _load_config()
    enabled_text = "ON" if config.enabled else "OFF"
    universe = ", ".join(config.universe) if config.universe else "alle"
    lines = [
        "<b>🤖 AI Gatekeeper</b>",
        f"Status: <code>{enabled_text}</code>",
        f"Modus: <code>{config.mode}</code>",
        f"Universe: <code>{universe}</code>",
        f"Min. Win-Rate: <code>{config.min_win_rate:.2f}</code>",
    ]

    if symbol:
        store = _get_store()
        stats = store.summary_for_symbol(symbol)
        if stats:
            lines.append(f"<b>Stats {symbol.upper()}</b>")
            for action, values in stats.items():
                wins = values.get("wins", 0)
                losses = values.get("losses", 0)
                total = wins + losses
                win_rate = wins / total if total else 0.0
                lines.append(
                    f"• {action}: {wins}W/{losses}L (WR {win_rate:.2f})"
                )
        else:
            lines.append("Keine Feedback-Daten für dieses Symbol.")

    store = _get_store()
    recent = store.recent_signals(limit=50)
    if recent:
        lines.append("<b>Letzte 50 Signale</b>")
        for entry in reversed(recent):
            symbol_text = str(entry.get("symbol") or "—").upper()
            actions = entry.get("actions") or []
            if not isinstance(actions, list):
                actions = [str(actions)]
            actions_text = ", ".join(str(item) for item in actions) or "—"
            blocked = entry.get("blocked") or []
            if not isinstance(blocked, list):
                blocked = [str(blocked)]
            blocked_text = ", ".join(str(item) for item in blocked) or "—"
            mode = entry.get("mode") or "—"
            reason = entry.get("reason") or "—"
            lines.append(
                f"• {symbol_text}: {actions_text} | blockiert: {blocked_text} "
                f"| mode: {mode} | reason: {reason}"
            )

    return "\n".join(lines)


def record_feedback(symbol: str, action: str, outcome: str) -> float:
    store = _get_store()
    return store.record_feedback(symbol, action, outcome)


def _should_evaluate_symbol(symbol: str, universe: Sequence[str]) -> bool:
    if not universe:
        return True
    return symbol.upper() in {item.upper() for item in universe}


def _score_action(symbol: str, action: str, store: LearningStore) -> float:
    win_rate = store.get_win_rate(symbol, action)
    if win_rate is None:
        return 0.5
    return win_rate


def evaluate_signal(
    symbol: str,
    actions: Sequence[str],
    *,
    payload: Optional[Dict[str, Any]] = None,
) -> AIDecision:
    config = _load_config()
    store = _get_store()
    evaluated_actions: list[str] = []
    allowed_actions: list[str] = []
    blocked_actions: list[str] = []

    if not config.enabled or config.mode == "off":
        decision = AIDecision(
            allowed_actions=list(actions),
            blocked_actions=[],
            mode=config.mode,
            reason="disabled",
            evaluated_actions=[],
        )
        store.log_signal(symbol, actions, decision, payload=payload)
        return decision

    if not _should_evaluate_symbol(symbol, config.universe):
        decision = AIDecision(
            allowed_actions=list(actions),
            blocked_actions=[],
            mode=config.mode,
            reason="symbol_not_in_universe",
            evaluated_actions=[],
        )
        store.log_signal(symbol, actions, decision, payload=payload)
        return decision

    score = None
    for action in actions:
        canonical = canonical_action(action)
        if canonical in CLOSE_ACTIONS or canonical not in OPEN_ACTIONS:
            allowed_actions.append(canonical)
            continue
        evaluated_actions.append(canonical)
        score = _score_action(symbol, canonical, store)
        if score >= config.min_win_rate:
            allowed_actions.append(canonical)
        else:
            blocked_actions.append(canonical)

    if config.mode == "shadow":
        decision = AIDecision(
            allowed_actions=list(actions),
            blocked_actions=blocked_actions,
            mode=config.mode,
            reason="shadow",
            evaluated_actions=evaluated_actions,
            score=score,
        )
    else:
        decision = AIDecision(
            allowed_actions=allowed_actions + [
                action
                for action in actions
                if canonical_action(action) not in OPEN_ACTIONS
                and canonical_action(action) not in CLOSE_ACTIONS
            ],
            blocked_actions=blocked_actions,
            mode=config.mode,
            reason="evaluated",
            evaluated_actions=evaluated_actions,
            score=score,
        )

    store.log_signal(symbol, actions, decision, payload=payload)
    return decision
