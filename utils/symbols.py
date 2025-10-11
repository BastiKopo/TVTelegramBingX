import re

__all__ = ["norm_symbol", "is_symbol"]

_SYM = re.compile(r"^[A-Z]{2,10}-?USDT$", re.I)


def norm_symbol(s: str) -> str:
    s = (s or "").upper().replace("_", "-")
    if s.endswith("USDT") and "-" not in s:
        s = s[:-4] + "-USDT"
    return s


def is_symbol(s: str) -> bool:
    return bool(_SYM.match((s or "").replace("-", "")))
