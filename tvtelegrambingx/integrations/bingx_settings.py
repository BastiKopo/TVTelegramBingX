import os

# Hotfix A: Leverage-Setzen global deaktiviert (Default)
ENABLE_SET_LEVERAGE = os.getenv("ENABLE_SET_LEVERAGE", "false").lower() == "true"


async def ensure_leverage(*_args, **_kwargs):
    """Legacy hook for leverage handling (now disabled)."""
    # no-op, wir wollen Leverage NICHT mehr setzen
    return {"skipped": True}
