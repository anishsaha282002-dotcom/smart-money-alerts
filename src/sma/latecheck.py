"""'Can you still copy it?' - replay a wallet's past buys through OHLCV.

For each past position we look up the candle close at the wallet's buy minute (or its own
fill price when the source gives one), at +5m and at +30m, and the price when the wallet
exited (or +4h if it never closed). The copier is assumed to exit when the wallet exits, but
never before entering: if the wallet was already out, the copied trade is counted as 0%
and flagged "too fast to copy". All numbers are before fees and slippage.
"""
from __future__ import annotations

import bisect

from .util import median

DELAYS = (0, 300, 1800)
OPEN_EXIT_S = 4 * 3600


def price_at(candles, ts):
    """Close of the last candle starting at or before ts. candles: sorted [(t,o,h,l,c,v)]."""
    if not candles:
        return None
    keys = [c[0] for c in candles]
    i = bisect.bisect_right(keys, ts) - 1
    if i < 0:
        return candles[0][1]          # before first candle: use first open
    if ts - candles[i][0] > 6 * 3600:
        return None                   # data gap too large to trust
    return candles[i][4]


def max_high_between(candles, a, b):
    hs = [c[2] for c in candles if a <= c[0] <= b]
    return max(hs) if hs else None


def replay_position(candles, buy_ts, exit_ts, own_buy_price=None):
    exit_ts = exit_ts or buy_ts + OPEN_EXIT_S
    p_exit = price_at(candles, exit_ts)
    out = {"buy_ts": buy_ts, "exit_ts": exit_ts}
    for d in DELAYS:
        entry_ts = buy_ts + d
        p_in = own_buy_price if (d == 0 and own_buy_price) else price_at(candles, entry_ts)
        key = {0: "at_buy", 300: "late_5m", 1800: "late_30m"}[d]
        if not p_in or not p_exit:
            out[key] = None
            continue
        if entry_ts >= exit_ts:
            out[key] = 0.0
            out.setdefault("too_fast", []).append(key)
        else:
            out[key] = p_exit / p_in - 1
    return out


def summarize(replays):
    s = {"n": len(replays)}
    for k in ("at_buy", "late_5m", "late_30m"):
        vals = [r[k] for r in replays if r.get(k) is not None]
        s[k] = median(vals)
        s[k + "_n"] = len(vals)
        s[k + "_win"] = (sum(1 for v in vals if v > 0) / len(vals)) if vals else None
    s["too_fast_5m"] = sum(1 for r in replays if "late_5m" in r.get("too_fast", []))
    return s


def forward_check(candles, buy_ts, buy_price, now_ts):
    """For a live alert: how far price already moved since the wallet's buy."""
    p_now = price_at(candles, now_ts)
    p0 = buy_price or price_at(candles, buy_ts)
    if not p_now or not p0:
        return {"moved_since_buy": None, "minutes_since_buy": round((now_ts - buy_ts) / 60, 1), "price_now": p_now}
    return {"moved_since_buy": p_now / p0 - 1, "minutes_since_buy": round((now_ts - buy_ts) / 60, 1),
            "price_now": p_now, "buy_price": p0}
