"""Utilities to migrate Freqtrade configuration files.

This helper currently focuses on moving the global
``pair_whitelist`` option into the ``StaticPairList`` definition. The
behaviour of Freqtrade 2025 switched to expecting the whitelist inside
the plugin's configuration block which breaks older configurations
that only defined the global key. The migration keeps the global value
for backwards compatibility while ensuring the plugin receives the
expected value as well.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class MigrationResult:
    """Return value containing the migrated data and a change flag."""

    data: Dict[str, Any]
    changed: bool


def _iter_static_pairlists(pairlists: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    """Yield every StaticPairList definition from the configuration."""

    for entry in pairlists:
        if isinstance(entry, dict) and entry.get("method") == "StaticPairList":
            yield entry


def migrate_static_pairlist_whitelist(config: Dict[str, Any]) -> MigrationResult:
    """Ensure ``pair_whitelist`` is configured for ``StaticPairList`` plugins.

    Newer Freqtrade releases expect the whitelist to be provided in the
    pairlist plugin configuration. Older configuration files relied on
    the global ``pair_whitelist`` key instead. This migration copies the
    global value into the plugin configuration when missing.
    """

    pairlists = config.get("pairlists")
    if not isinstance(pairlists, list):
        return MigrationResult(config, False)

    whitelist = config.get("pair_whitelist")
    if not whitelist:
        return MigrationResult(config, False)

    changed = False
    for entry in _iter_static_pairlists(pairlists):
        cfg = entry.get("config")
        if cfg is None:
            cfg = {}
            entry["config"] = cfg
            changed = True

        if isinstance(cfg, dict) and "pair_whitelist" not in cfg:
            cfg["pair_whitelist"] = whitelist
            changed = True

    return MigrationResult(config, changed)


def migrate_file(path: Path) -> MigrationResult:
    """Load, migrate, and optionally rewrite a Freqtrade configuration file."""

    data = Path(path).read_text(encoding="utf-8")
    config = json.loads(data)
    result = migrate_static_pairlist_whitelist(config)
    if result.changed:
        Path(path).write_text(
            json.dumps(result.data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


__all__ = [
    "MigrationResult",
    "migrate_file",
    "migrate_static_pairlist_whitelist",
]
