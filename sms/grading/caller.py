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


def grade_callers(mentions: list[Call], histories: dict[str, list[Call]], min_followers: int = 0) -> CallerGrade:
    """Grade for one coin: who mentioned it, and what each of them is worth listening to."""
    seen: dict[str, Call] = {}
    for m in sorted(mentions, key=lambda c: c.ts):
        if m.followers is not None and m.followers < min_followers:
            continue
        seen.setdefault(m.caller, m)            # a caller's first mention is the call
    if not seen:
        return CallerGrade(grade=None, n_callers=0, note="No tracked caller has mentioned it yet.")

    callers = []
    for name, first in seen.items():
        g = grade_caller(histories.get(name, []))
        callers.append({"caller": name, "called_ts": first.ts, "followers": first.followers, **g})
    rated = [c for c in callers if c["grade"]]
    callers.sort(key=lambda c: (c["score"] is None, -(c["score"] or 0)))
    if not rated:
        return CallerGrade(grade=None, n_callers=len(callers), callers=callers,
                           note="Mentioned, but none of these callers has enough aged calls to rate.")
    score = statistics.median(c["score"] for c in rated)
    grade = next((g for g, floor in THRESHOLDS if score >= floor), "D")
    return CallerGrade(grade=grade, n_callers=len(callers), callers=callers,
                       note=f"Median of {len(rated)} rated caller{'s' if len(rated) != 1 else ''}.")
