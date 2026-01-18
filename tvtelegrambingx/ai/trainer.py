"""Daily AI policy update task."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from tvtelegrambingx.ai.gatekeeper import LearningStore, _load_config
from tvtelegrambingx.config import Settings

LOGGER = logging.getLogger(__name__)


async def run_ai_trainer(settings: Settings) -> None:
    """Run the daily AI policy update loop."""
    if not settings.ai_learning_enabled:
        LOGGER.info("AI learning disabled; trainer stopped")
        return

    store_path = Path(settings.ai_store_path) if settings.ai_store_path else Path.home() / ".tvtelegrambingx_ai.json"
    store = LearningStore(store_path)
    interval_seconds = max(1, settings.ai_learning_interval_hours) * 3600

    while True:
        try:
            config = _load_config()
            if config.mode == "advanced":
                now = int(time.time())
                since_ts = now - (7 * 24 * 3600)
                policy = store.update_policy(since_ts=since_ts)
                LOGGER.info("AI policy updated: %s symbols", len(policy))
            else:
                LOGGER.debug("AI policy update skipped (mode=%s)", config.mode)
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("AI policy update failed")

        await asyncio.sleep(interval_seconds)
