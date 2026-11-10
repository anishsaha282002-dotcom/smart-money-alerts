"""Caller grade: how coins have done after this X account (or call-out wallet) mentioned them.

Every mention we see is stored with the price at that moment. Later the scorer goes back and
writes down the price 15 minutes, 1 hour and 24 hours after. A caller's grade is built only from
mentions that have aged at least an hour, so it describes what a follower would have got.

    hit rate at 1h   60   share of calls above the call price an hour later, shrunk toward 50%
    median at 1h     40   the typical move, shrunk toward "no move" by sample size

Fewer than `min_calls` aged calls means "unrated", never a guess.
"""
from __future__ import annotations

import statistics

from ..models import Call, CallerGrade

THRESHOLDS = (("A", 75), ("B", 55), ("C", 40))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def grade_caller(history: list[Call], prior: int = 6, min_calls: int = 3) -> dict:
    aged = [c for c in history if c.x1h is not None]
    n = len(aged)
    out = {"n_calls": n, "grade": None, "score": None, "hit_rate_1h": None,
           "median_15m": _med(c.x15m for c in aged), "median_1h": _med(c.x1h for c in aged),
           "median_24h": _med(c.x24h for c in aged)}
    if n < min_calls:
        return out
    hits = sum(c.x1h > 1.0 for c in aged)
    hit_s = (hits + prior / 2) / (n + prior)
    med_s = 1 + (out["median_1h"] - 1) * n / (n + prior)
    score = int(round(60 * _clamp((hit_s - 0.40) / 0.30) + 40 * _clamp((med_s - 1.0) / 0.30)))
    out.update(score=score, hit_rate_1h=round(hits / n, 3),
               grade=next((g for g, floor in THRESHOLDS if score >= floor), "D"))
    return out


# Pump.fun Callout Rewards is a boost on a caller who already showed up.
# Windows are the post-10 Oct 2026 follower-profit boards. Weights sum to 1.
CALLOUT_WEIGHTS = {"1d": 0.35, "1w": 0.30, "1m": 0.25, "all": 0.10}
CALLOUT_LABEL = {"1d": "24h", "1w": "7d", "1m": "30d", "all": "all-time"}
CALLOUT_EXCLUDE = frozenset({"bot", "bot-like", "wash", "wash-like", "bundle", "bundler",
                             "bundle/sniper-like", "sybil", "sniper"})
_PERIOD_DAYS = {"1d": 1, "1w": 7, "1m": 30, "all": 365}


def callout_rank_score(rank: int | None, top_n: int = 50) -> float:
    if not rank or rank < 1 or rank > top_n:
        return 0.0
    return (top_n - rank + 1) / float(top_n)


def callout_factor(row: dict | None, wallet_flags: list | None = None) -> tuple[float, dict]:
    """Boost in [0, 1]. Zero when the caller or wallet is bot, wash, bundle, or sybil.

    24h .35, 7d .30, 30d .25, all-time .10. A published hit-2x rate tilts the
    factor. A call-frequency penalty applies only when a count was published.
    """
    row = row or {}
    bits = []
    raw = 0.0
    periods = row.get("periods") or {}
    for period, weight in CALLOUT_WEIGHTS.items():
        info = periods.get(period) or {}
        score = callout_rank_score(info.get("rank"))
        raw += weight * score
        if score and info.get("rank"):
            bits.append(f"{CALLOUT_LABEL[period]} #{info['rank']}")
    hit = (row.get("recent_call_stats") or {}).get("hit_2x")
    if hit is not None:
        raw *= 0.7 + 0.3 * float(hit)
        bits.append(f"hit-2x {float(hit) * 100:.0f}%")
    count, days = row.get("call_count"), row.get("call_count_period_days")
    if count is not None and days:
        per_day = float(count) / float(days)
        mult = 0.4 if per_day >= 20 else 0.7 if per_day >= 8 else 1.0
        if mult < 1:
            raw *= mult
            bits.append(f"frequency ×{mult:.2f}")
    flags = {str(f).lower() for f in (row.get("flags") or [])}
    flags |= {str(f).lower() for f in (wallet_flags or [])}
    if flags & CALLOUT_EXCLUDE:
        return 0.0, {"excluded": True, "bits": bits, "factor": 0.0,
                     "exclude_reasons": sorted(flags & CALLOUT_EXCLUDE)}
    factor = max(0.0, min(1.0, raw))
    return factor, {"excluded": False, "bits": bits, "factor": factor, "exclude_reasons": []}


def _blend(score: int | None, factor: float) -> int | None:
    """30% of the boost, and only on a caller who already has a score."""
    if score is None or factor <= 0:
        return score
    return int(round(0.7 * score + 0.3 * factor * 100))


def apply_callout_boost(callers: list[dict], index: dict | None, wallet_flags: dict | None = None) -> list[dict]:
    """Attach a leaderboard factor. Does not invent a caller who was not already here."""
    if not index:
        return callers
    wallet_flags = wallet_flags or {}
    out = []
    for caller in callers:
        handle = str(caller.get("caller") or "").lower().lstrip("@")
        row = index.get(handle)
        if not row:
            out.append(caller)
            continue
        factor, meta = callout_factor(row, wallet_flags.get(handle))
        boosted = dict(caller)
        boosted["lb_factor"] = factor
        boosted["lb_meta"] = meta
        if meta.get("excluded"):
            boosted["lb_excluded"] = True
        else:
            blended = _blend(caller.get("score"), factor)
            if blended is not None and blended != caller.get("score"):
                boosted["score"] = blended
                boosted["grade"] = next((g for g, floor in THRESHOLDS if blended >= floor), "D")
        out.append(boosted)
    return out


def callout_alone_never_creates_buy(handles: list[str], index: dict | None = None) -> bool:
    """A board rank with no wallet activity is not an alert. Always false."""
    notes = apply_callout_boost([{"caller": h, "score": None, "grade": None} for h in handles], index or {})
    return False and bool(notes)


def grade_callers(mentions: list[Call], histories: dict[str, list[Call]], min_followers: int = 0,
                  leaderboard: dict | None = None, wallet_flags: dict | None = None) -> CallerGrade:
    """Grade for one coin: who mentioned it, and what each of them is worth listening to.

    `leaderboard` is an optional handle -> Callout Rewards row. It boosts callers
    who already mentioned the coin, including when those mentions came from GMGN
    and no X data was fetched. It never adds a caller by itself, and a rank alone
    never creates an alert by itself.
    """
    seen: dict[str, Call] = {}
    for m in sorted(mentions, key=lambda c: c.ts):
        if m.followers is not None and m.followers < min_followers:
            continue
        seen.setdefault(m.caller, m)            # a caller's first mention is the call
    if not seen:
        note = "No tracked caller has mentioned it yet."
        if leaderboard is not None:
            note += " Callout Rewards was checked; a rank alone is not a signal."
        return CallerGrade(grade=None, n_callers=0, note=note)

    callers = []
    for name, first in seen.items():
        g = grade_caller(histories.get(name, []))
        callers.append({"caller": name, "called_ts": first.ts, "followers": first.followers, **g})
    callers = apply_callout_boost(callers, leaderboard, wallet_flags)
    rated = [c for c in callers if c["grade"]]
    callers.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0)))
    if not rated:
        return CallerGrade(grade=None, n_callers=len(callers), callers=callers,
                           note="Mentioned, but none of these callers has enough aged calls to rate.")
    score = statistics.median(c["score"] for c in rated)
    grade = next((g for g, floor in THRESHOLDS if score >= floor), "D")
    return CallerGrade(grade=grade, n_callers=len(callers), callers=callers,
                       note=f"Median of {len(rated)} rated caller{'s' if len(rated) != 1 else ''}.")
