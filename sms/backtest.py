"""Measure what happened after past signals, so an alert can say how similar alerts turned out.

Pure functions, no network: give it signals (mint, ts, kind) and 5-minute candles
(ts, open, high, low, close), get back forward returns per signal and hit rates per signal kind.

Honesty rules baked in:
  * the entry is the close of the candle that contains the signal time (what a reader could
    roughly have had a few minutes later), never the wallet's own fill;
  * a signal without candles is counted as `unpriced` and reported, not silently dropped;
  * a horizon is only scored once the full window has passed (`now`), so young signals do not
    count as non-events;
  * "reached 2x" uses candle highs and "fell 50%" uses candle lows inside the window, so they are
    best/worst cases that a real trade would rarely capture exactly.

This produces history, not a forecast, and never a buy or sell instruction.
"""
from __future__ import annotations

import statistics

FWD_HORIZONS = {"1h": 3600, "6h": 6 * 3600, "24h": 86400}
MIN_SAMPLE = 30   # fewer signals than this in a bucket is shown as "not enough history"


def entry_candle(candles: list, ts: int, step: int = 300):
    """The candle containing ts (or the first one after it, within one step)."""
    for c in candles:
        if c[0] <= ts < c[0] + step:
            return c
    after = [c for c in candles if ts <= c[0] <= ts + step]
    return after[0] if after else None


def forward(candles: list, ts: int, now: int, step: int = 300) -> dict | None:
    """Forward stats from the signal time. None when there is no entry candle."""
    candles = sorted(candles, key=lambda c: c[0])
    e = entry_candle(candles, ts, step)
    if not e or not e[4]:
        return None
    entry = float(e[4])
    out = {"entry": entry}
    for h, secs in FWD_HORIZONS.items():
        end = ts + secs
        if now < end:
            out[h] = None            # window not closed yet
            continue
        win = [c for c in candles if e[0] < c[0] <= end]
        if not win:
            # nobody traded after entry: the price did not move as far as the data shows
            out[h] = {"x": 1.0, "peak_x": 1.0, "low_x": 1.0, "quiet": True}
            continue
        last = float(win[-1][4])
        peak = max(float(c[2]) for c in win)
        low = min(float(c[3]) for c in win)
        out[h] = {"x": round(last / entry, 4), "peak_x": round(max(peak, last) / entry, 4),
                  "low_x": round(min(low, last) / entry, 4), "quiet": False}
    return out


def max_drawdown(candles: list, ts: int, horizon_s: int, step: int = 300) -> float | None:
    """Worst peak-to-trough fall after entry within the horizon, as a fraction (0.6 = -60%)."""
    candles = sorted(candles, key=lambda c: c[0])
    e = entry_candle(candles, ts, step)
    if not e:
        return None
    peak, worst = float(e[4]), 0.0
    for c in candles:
        if e[0] < c[0] <= ts + horizon_s:
            peak = max(peak, float(c[2]))
            if peak:
                worst = max(worst, 1 - float(c[3]) / peak)
    return round(worst, 4)


def summarize(results: list[dict], horizon: str = "24h") -> dict:
    """Hit rates for one bucket of signals at one horizon."""
    scored = [r[horizon] for r in results if r and r.get(horizon)]
    n = len(scored)
    if not n:
        return {"n": 0}
    xs = [s["x"] for s in scored]
    return {
        "n": n,
        "pct_2x": round(sum(s["peak_x"] >= 2 for s in scored) / n, 4),
        "pct_down50": round(sum(s["low_x"] <= 0.5 for s in scored) / n, 4),
        "pct_up_at_end": round(sum(x > 1 for x in xs) / n, 4),
        "median_x": round(statistics.median(xs), 4),
        "mean_x": round(statistics.fmean(xs), 4),
    }


def two_x_before_half(candles: list, ts: int, horizon_s: int, step: int = 300) -> bool | None:
    """Did it touch 2x before it touched -50%? (The order a reader cares about.) None if no entry."""
    candles = sorted(candles, key=lambda c: c[0])
    e = entry_candle(candles, ts, step)
    if not e or not e[4]:
        return None
    entry = float(e[4])
    for c in candles:
        if e[0] < c[0] <= ts + horizon_s:
            lo_hit, hi_hit = float(c[3]) <= entry * 0.5, float(c[2]) >= entry * 2
            if lo_hit and hi_hit:
                return False          # same candle: assume the worse order
            if hi_hit:
                return True
            if lo_hit:
                return False
    return False


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k hits out of n, so small buckets show how unsure they are."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round((c - r) / d, 4), round((c + r) / d, 4))
