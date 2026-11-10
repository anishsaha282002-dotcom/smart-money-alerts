"""Formatting helpers used by stories, the CLI and the exports."""
from __future__ import annotations

import statistics


def usd(v: float | None, dash: str = "—") -> str:
    if v is None:
        return dash
    a = abs(v)
    if a >= 1e9:
        s = f"${a / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"${a / 1e6:.2f}M"
    elif a >= 1e4:
        s = f"${a / 1e3:.0f}K"
    elif a >= 1e3:
        s = f"${a / 1e3:.1f}K"
    else:
        s = f"${a:,.0f}"
    return ("-" if v < 0 else "") + s


def signed_usd(v: float | None) -> str:
    if v is None:
        return "—"
    return ("+" if v >= 0 else "") + usd(v)


def pct(x: float | None, digits: int = 0, signed: bool = True) -> str:
    """A multiple (1.42) as a percentage change (+42%)."""
    if x is None:
        return "—"
    v = (x - 1) * 100
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def share(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        h, m = divmod(s // 60, 60)
        return f"{h}h {m:02d}m" if m else f"{h}h"
    return f"{s // 86400}d"


def median(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1:
        return f"${p:,.2f}"
    if p >= 0.01:
        return f"${p:.4f}"
    return f"${p:.3g}"
