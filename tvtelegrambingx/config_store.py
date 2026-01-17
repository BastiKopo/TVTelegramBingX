"""Persistent configuration storage for runtime trading parameters."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_CONFIG: Dict[str, Any] = {
    "_global": {
        "auto_trade": False,
        "bot_enabled": True,
    },
    "symbols": {},
}


class ConfigStore:
    """Small JSON-backed key/value store for runtime configuration."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        base_path = Path(path) if path is not None else Path.home() / ".tvtelegrambingx_config.json"
        self._path = base_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self._path.exists():
            self._write(dict(_DEFAULT_CONFIG))

    def _read(self) -> Dict[str, Any]:
        with self._lock:
            try:
                raw = self._path.read_text(encoding="utf-8")
            except FileNotFoundError:
                data = dict(_DEFAULT_CONFIG)
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(
                    json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False),
                    encoding="utf-8",
                )
                return data
            except OSError:
                return dict(_DEFAULT_CONFIG)

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = dict(_DEFAULT_CONFIG)

            if "_global" not in data or not isinstance(data["_global"], dict):
                data["_global"] = {}
            if "symbols" not in data or not isinstance(data["symbols"], dict):
                data["symbols"] = {}

            for key, value in _DEFAULT_CONFIG["_global"].items():
                data["_global"].setdefault(key, value)

            return data

    def _write(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            self._path.write_text(serialized, encoding="utf-8")

    def get(self) -> Dict[str, Any]:
        """Return the full configuration structure."""
        return self._read()

    def set_global(self, **kwargs: Any) -> None:
        data = self._read()
        data["_global"].update({k: v for k, v in kwargs.items() if v is not None})
        self._write(data)

    def set_symbol(self, symbol: str, **kwargs: Any) -> None:
        data = self._read()
        data.setdefault("symbols", {})
        symbol_key = symbol.upper()
        data["symbols"].setdefault(symbol_key, {})
        data["symbols"][symbol_key].update({k: v for k, v in kwargs.items() if v is not None})
        self._write(data)

    def get_effective(self, symbol: str) -> Dict[str, Any]:
        data = self._read()
        symbol_key = symbol.upper()
        effective = dict(data.get("_global", {}))
        symbol_data = data.get("symbols", {}).get(symbol_key, {})
        effective.update(symbol_data)
        return effective

    def get_auto_trade(self, symbol: Optional[str] = None) -> bool:
        """Return whether auto trading is enabled globally or for a symbol."""

        data = self._read()
        if symbol:
            symbol_key = symbol.upper()
            symbol_cfg = data.get("symbols", {}).get(symbol_key)
            if isinstance(symbol_cfg, dict) and "auto_trade" in symbol_cfg:
                return bool(symbol_cfg.get("auto_trade"))

        return bool(data.get("_global", {}).get("auto_trade", False))

    def get_bot_enabled(self) -> bool:
        """Return whether the bot should accept signals globally."""

        data = self._read()
        return bool(data.get("_global", {}).get("bot_enabled", True))
