"""Caller grade from X chatter.

Each tracked caller (data/callers.json) gets a hit rate = share of their detected calls whose
24h peak reached 2x. Until this tool has tracked enough of their calls itself, a published
'NN% of MM' figure in the caller's note is used as a weak prior (counted at 1/3 weight), and
everything is shrunk toward a 30% base rate. Flagged accounts and catalysts never count.
"""
from __future__ import annotations

import re

BASE_RATE = 0.30
SHRINK = 10
_PRIOR_RE = re.compile(r"(\d{1,3})%\s*(?:hit-2x\s*)?(?:of|over last)\s*(\d{1,4})")


def load_callers(j):
    out = {}
    for c in j.get("callers", []):
        h = c["handle"].lower()
        prior = None
        m = _PRIOR_RE.search(c.get("note") or "")
        if m:
            prior = (int(m.group(1)) / 100.0, int(m.group(2)))
        out[h] = {"handle": c["handle"], "tier": c.get("tier", "B"), "lang": c.get("lang", "en"), "prior": prior}
    return out


def caller_rate(info, tracked_hits=0, tracked_n=0):
    hits, n = float(tracked_hits), float(tracked_n)
    if info.get("prior"):
        p, m = info["prior"]
        w = m / 3.0
        hits += p * w
        n += w
    rate = (hits + BASE_RATE * SHRINK) / (n + SHRINK)
    return rate, n


def rate_grade(rate):
    return "A" if rate >= 0.55 else "B" if rate >= 0.42 else "C" if rate >= 0.32 else "D"


def grade_chatter(posts, callers, tracked=None, window_h=6):
    """posts: [{author, text, ts}] that mention the token. Returns a dict for the alert."""
    tracked = tracked or {}
    by_caller = {}
    for p in posts:
        h = (p.get("author") or "").lower()
        if h in callers and h not in by_caller:
            info = callers[h]
            th, tn = tracked.get(h, (0, 0))
            rate, n_eff = caller_rate(info, th, tn)
            by_caller[h] = {"handle": info["handle"], "rate": rate, "n_eff": round(n_eff, 1),
                            "grade": rate_grade(rate), "tracked_n": tn, "ts": p.get("ts"),
                            "prior": info.get("prior")}
    callers_hit = sorted(by_caller.values(), key=lambda c: -c["rate"])
    if not posts:
        grade = "D"
    elif not callers_hit:
        grade = "C" if len(posts) >= 20 else "D"
    else:
        best = callers_hit[0]["grade"]
        grade = best
        if len(callers_hit) >= 3 and best in ("B", "C"):
            grade = {"B": "A", "C": "B"}[best]   # three+ independent tracked callers bumps one step
    return {"checked": True, "grade": grade, "posts": len(posts), "callers": callers_hit[:5],
            "window_h": window_h}


NOT_CHECKED = {"checked": False, "grade": None, "posts": 0, "callers": [], "reason": "no X_BEARER_TOKEN set"}
