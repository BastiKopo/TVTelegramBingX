def norm_symbol(s: str) -> str:
    s = (s or "").upper().replace("_", "-")
    if s.endswith("USDT") and "-" not in s:
        s = s[:-4] + "-USDT"
    return s
