"""'Can you still copy it?' — what was left for someone who bought after the wallet did.

Given 1-minute candles from the wallet's buy onward:

    wallet_x   best the wallet's own entry reached inside the window (peak ÷ its price)
    entry_x    how much more a copier paid, 5 and 30 minutes later (price then ÷ wallet's price)
    left_x     best a copier could still have reached (later peak ÷ copier's price)
    kept       share of the wallet's upside still on the table: (left_x − 1) ÷ (wallet_x − 1)

Everything is measured to the *peak*, which nobody sells at. So these are ceilings: if even the
ceiling says "mostly gone", it was gone.
"""
from __future__ import annotations

import statistics

WINDOW = 4 * 3600
DELAYS = {"5m": 300, "30m": 1800}
RAN = 1.05                      # the wallet's entry has to gain 5% before "upside" means anything


def price_at(candles: list[list], ts: int) -> float | None:
    """Close of the last candle that started at or before `ts`."""
    last = None
    for c in candles:
        if c[0] <= ts:
            last = c[4]
        else:
            break
    return last


def peak_between(candles: list[list], start: int, end: int) -> float | None:
    highs = [c[2] for c in candles if start < c[0] <= end]
    return max(highs) if highs else None


def low_between(candles: list[list], start: int, end: int) -> float | None:
    lows = [c[3] for c in candles if start < c[0] <= end]
    return min(lows) if lows else None


def copy_check(candles: list[list], t0: int, p0: float | None, window: int = WINDOW, now: int | None = None) -> dict | None:
    """None when there is not enough data to say anything."""
    candles = sorted(candles, key=lambda c: c[0])
    if not candles or not p0 or p0 <= 0:
        return None
    end = t0 + window
    if now is not None and now < t0 + DELAYS["30m"]:
        return None
    covered = candles[-1][0] - t0
    if covered < DELAYS["30m"]:
        return None
    peak0 = peak_between(candles, t0, end)
    if peak0 is None:
        return None
    wallet_x = max(peak0 / p0, 1.0)
    out: dict = {"wallet_x": round(wallet_x, 3), "window_h": window // 3600,
                 "complete": covered >= window or (now is not None and now >= end)}
    for name, delay in DELAYS.items():
        p = price_at(candles, t0 + delay)
        peak = peak_between(candles, t0 + delay, end)
        if not p or peak is None:
            out[name] = None
            continue
        left_x = max(peak / p, 1.0)
        kept = max(0.0, min(1.0, (left_x - 1) / (wallet_x - 1))) if wallet_x >= RAN else None
        out[name] = {"entry_x": round(p / p0, 3), "left_x": round(left_x, 3),
                     "kept": round(kept, 3) if kept is not None else None}
    out["verdict"] = verdict(out)
    # the first hour as ~40 points relative to the wallet's price, for the small chart
    hour = [c for c in candles if t0 <= c[0] <= t0 + 3600]
    step = max(1, -(-len(hour) // 40))
    out["spark"] = [round(c[4] / p0, 3) for c in hour[::step]]
    return out


def verdict(check: dict) -> str:
    if check["wallet_x"] < RAN:
        return "never-ran"
    k5 = (check.get("5m") or {}).get("kept")
    if k5 is None:
        return "unknown"
    if k5 >= 0.60:
        return "mostly-there"
    if k5 >= 0.25:
        return "partly-gone"
    return "mostly-gone"


VERDICT_TEXT = {
    "mostly-there": "most of the move was still there 5 minutes later",
    "partly-gone": "a good part of the move was gone within 5 minutes",
    "mostly-gone": "mostly gone within 5 minutes",
    "never-ran": "the wallet's own buy never got going",
    "unknown": "not enough price data",
}


def summarize(checks: list[dict]) -> dict | None:
    """The wallet's history as medians. Buys that never ran are counted, not dropped."""
    checks = [c for c in checks if c]
    if not checks:
        return None

    def med(delay: str, field: str):
        xs = [(c.get(delay) or {}).get(field) for c in checks]
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 3) if xs else None

    ran = [c for c in checks if c["wallet_x"] >= RAN]
    out = {"n": len(checks), "n_ran": len(ran),
           "wallet_x": round(statistics.median(c["wallet_x"] for c in checks), 3)}
    for d in DELAYS:
        out[d] = {"entry_x": med(d, "entry_x"), "left_x": med(d, "left_x"), "kept": med(d, "kept")}
    k5 = out["5m"]["kept"]
    out["verdict"] = ("never-ran" if not ran else "unknown" if k5 is None else
                      "mostly-there" if k5 >= 0.60 else "partly-gone" if k5 >= 0.25 else "mostly-gone")
    return out
