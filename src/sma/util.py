from __future__ import annotations

import datetime as dt
import math
import statistics


def utc_iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def fnum(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pct(x, digits=0) -> str:
    if x is None:
        return "n/a"
    v = round(x * 100, digits)
    return f"{0.0 if v == 0 else v:+.{digits}f}%"


def short(addr: str, n=4) -> str:
    if not addr:
        return "?"
    return addr if len(addr) <= 2 * n + 1 else f"{addr[:n]}…{addr[-n:]}"


def human_usd(x) -> str:
    x = fnum(x)
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:.1f}{unit}"
    return f"${x:,.0f}"


def human_dur(seconds) -> str:
    s = fnum(seconds)
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    if s < 172800:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def norm_addr(chain: str, addr: str) -> str:
    if not addr:
        return ""
    return addr if chain == "solana" else addr.lower()
