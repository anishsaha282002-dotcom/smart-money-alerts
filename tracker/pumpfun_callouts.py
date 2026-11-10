"""Read-only pump.fun Callout Rewards leaderboard helper.

Loads a dated snapshot (data/pumpfun_callout_leaderboard.json) and optionally
tries public JSON endpoints to refresh it. Never trades, never signs, never
invents numbers. Leaderboard ranks only BOOST an existing signal — a call or a
board rank alone must never create a BUY (see callout_alone_never_creates_buy).
"""
from __future__ import annotations

import json, os, urllib.request, urllib.error
from pathlib import Path

PERIODS = ("1d", "1w", "1m", "all")
# Post-10 Oct 2026 windows (follower-profit metric) outweigh all-time, which
# still includes earlier volume-era earnings. Weights sum to 1.
PERIOD_WEIGHTS = {"1d": 0.35, "1w": 0.30, "1m": 0.25, "all": 0.10}
PERIOD_LABEL = {"1d": "24h", "1w": "7-day", "1m": "30-day", "all": "all-time"}
TOP_N = 50
# Frequency penalty (Oct 4, 2026 change) only when a source published a call count.
HIGH_FREQ_PER_DAY = 8
VERY_HIGH_FREQ_PER_DAY = 20
WALLET_EXCLUDE_FLAGS = frozenset({"bot-like", "wash-like", "bundle/sniper-like", "sybil"})

# Official / live URLs we try first; all were Cloudflare-blocked from this
# environment on 9–10 Nov 2026. Snapshot URLs are the working public fallback.
OFFICIAL_TRY = [
    "https://frontend-api-v3.pump.fun/leaderboards/rewards?period=ALL",
    "https://frontend-api-v3.pump.fun/payouts/leaderboard",
    "https://frontend-api-v3.pump.fun/callouts/leaderboard",
]
SNAPSHOT_URLS = {
    "all": "https://calledcard.fun/data/lb_all.json",
    "1m": "https://calledcard.fun/data/lb_1m.json",
    "1w": "https://calledcard.fun/data/lb_1w.json",
    "1d": "https://calledcard.fun/data/lb_1d.json",
}
UA = {"User-Agent": "smart-money-alerts/0.1 (research; read-only callout leaderboard)"}


def default_snapshot_path(*anchors):
    env = (os.environ.get("PUMPFUN_CALLOUT_LEADERBOARD") or "").strip()
    if env:
        return Path(env)
    for a in anchors:
        if not a:
            continue
        p = Path(a)
        if p.is_file():
            return p
        # directory hints
        for cand in (
            p / "data" / "pumpfun_callout_leaderboard.json",
            p / "pumpfun_callout_leaderboard.json",
            p.parent / "data" / "pumpfun_callout_leaderboard.json",
        ):
            if cand.is_file():
                return cand
    here = Path(__file__).resolve()
    # sma: src/sma/sources/this.py -> repo root is parents[3]
    # tracker: tracker/this.py -> this directory is parent, repo root is parents[1]
    for cand in (
        here.parent / "data" / "pumpfun_callout_leaderboard.json",
        here.parents[1] / "data" / "pumpfun_callout_leaderboard.json",
        here.parents[3] / "data" / "pumpfun_callout_leaderboard.json" if len(here.parents) > 3 else None,
        Path.cwd() / "data" / "pumpfun_callout_leaderboard.json",
    ):
        if cand is not None and cand.is_file():
            return cand
    return here.parent / "data" / "pumpfun_callout_leaderboard.json"


def load_snapshot(path=None):
    p = Path(path) if path else default_snapshot_path()
    if not p.is_file():
        return {"callers": [], "n_callers": 0, "path": str(p), "loaded": False}
    data = json.loads(p.read_text(encoding="utf-8"))
    data["path"] = str(p)
    data["loaded"] = True
    return data


def _keys(row):
    out = []
    if row.get("x_handle"):
        out.append(row["x_handle"].lower().lstrip("@"))
    if row.get("username"):
        out.append(row["username"].lower())
    return out


def index_callers(snap):
    """Map lowercase X handle and pump.fun username to a caller row."""
    idx = {}
    for row in (snap or {}).get("callers") or []:
        for k in _keys(row):
            idx.setdefault(k, row)
    return idx


def rank_score(rank, top_n=TOP_N):
    if not rank or rank < 1 or rank > top_n:
        return 0.0
    return (top_n - rank + 1) / float(top_n)


def frequency_multiplier(call_count, period_days):
    """1.0 when call_count is unknown (do not invent a penalty)."""
    if call_count is None or not period_days or period_days <= 0:
        return 1.0
    cpd = call_count / float(period_days)
    if cpd >= VERY_HIGH_FREQ_PER_DAY:
        return 0.4
    if cpd >= HIGH_FREQ_PER_DAY:
        return 0.7
    return 1.0


def wallet_is_excluded(flags):
    flags = set(flags or [])
    return bool(flags & WALLET_EXCLUDE_FLAGS)


def leaderboard_factor(row, wallet_flags=None, period_weights=None):
    """Return (factor in [0, 1], reason bits) for one snapshot row.

    24h / 7-day / 30-day ranks (post-Oct 10 snapshots) outweigh all-time.
    A published last-100 hit-2x rate, if present, is a modest quality tilt.
    High call frequency and sybil/wash/bundle wallet flags reduce or zero it.
    """
    bits = []
    weights = period_weights or PERIOD_WEIGHTS
    raw = 0.0
    periods = (row or {}).get("periods") or {}
    for period, w in weights.items():
        info = periods.get(period)
        if not info:
            continue
        s = rank_score(info.get("rank"))
        raw += w * s
        if s:
            bits.append(f"{PERIOD_LABEL[period]} #{info['rank']} ({info['reward_usdc']:.0f} USDC)")
    later = (row or {}).get("all_time_later")
    # If calledcard all-time is missing but a later (rounded) all-time rank exists,
    # use it for the all-time slot only.
    if not periods.get("all") and later and later.get("rank"):
        s = rank_score(later["rank"])
        raw += weights.get("all", 0) * s
        bits.append(f"all-time #{later['rank']} ({later.get('reward_display') or ''} as of later board)".strip())
    stats = (row or {}).get("recent_call_stats") or {}
    hit = stats.get("hit_2x")
    if hit is not None:
        raw *= 0.7 + 0.3 * float(hit)
        bits.append(f"last-100 2x-hit {hit * 100:.0f}%")
    freq = frequency_multiplier(row.get("call_count") if row else None, row.get("call_count_period_days") if row else None)
    if freq < 1:
        raw *= freq
        bits.append(f"high-frequency penalty ×{freq:.2f}")
    flags = list((row or {}).get("flags") or [])
    if wallet_flags:
        flags.extend(wallet_flags)
    if wallet_is_excluded(flags):
        bad = sorted(set(flags) & WALLET_EXCLUDE_FLAGS)
        return 0.0, {"excluded": True, "exclude_reasons": bad, "bits": bits, "factor": 0.0}
    factor = max(0.0, min(1.0, raw))
    return factor, {"excluded": False, "exclude_reasons": [], "bits": bits, "factor": factor}


def lookup(idx, handle=None, username=None):
    for key in (handle, username):
        if not key:
            continue
        row = idx.get(str(key).lower().lstrip("@"))
        if row:
            return row
    return None


def merge_rate(hit_rate, factor, hit_weight=0.7, lb_weight=0.3):
    """Blend the existing 24h-2x hit rate with the leaderboard factor."""
    if factor is None:
        return hit_rate
    return hit_weight * float(hit_rate) + lb_weight * float(factor)


def boost_note_for_handles(handles, idx=None, snap=None, wallet_flags_by_handle=None):
    """Plain-English boost note, or None. Never implies a BUY by itself."""
    idx = idx if idx is not None else index_callers(snap or {})
    wallet_flags_by_handle = wallet_flags_by_handle or {}
    parts = []
    best = 0.0
    for h in handles or []:
        row = lookup(idx, handle=h, username=h)
        if not row:
            continue
        flags = wallet_flags_by_handle.get(str(h).lower().lstrip("@"))
        factor, meta = leaderboard_factor(row, wallet_flags=flags)
        if meta.get("excluded"):
            parts.append(f"@{row.get('x_handle') or row.get('username')} flagged on callout board ({', '.join(meta['exclude_reasons'])}; not used as a boost)")
            continue
        if factor <= 0:
            continue
        best = max(best, factor)
        who = row.get("x_handle") or row.get("username")
        detail = "; ".join(meta["bits"][:4]) if meta["bits"] else ""
        parts.append(f"@{who} pump.fun callout leaderboard factor {factor:.2f}" + (f" — {detail}" if detail else ""))
    if not parts:
        return None, 0.0
    return "Callout leaderboard (boost only, not a BUY by itself): " + "; ".join(parts), best


def apply_callout_boost(passes, fails, sig_type, handles, snap=None, idx=None, wallet_flags_by_handle=None):
    """Attach a leaderboard boost note. Does not create sig_type or clear fails."""
    passes = list(passes or [])
    fails = list(fails or [])
    note, factor = boost_note_for_handles(handles, idx=idx, snap=snap, wallet_flags_by_handle=wallet_flags_by_handle)
    if note:
        passes.append(note)
    return passes, fails, sig_type, factor


def would_buy(fails, sig_type):
    """BUY requires an existing signal type and zero failing filters."""
    return (not fails) and sig_type in ("caller", "narrative")


def callout_alone_never_creates_buy(handles, snap=None, idx=None):
    """Invariant: leaderboard handles alone, with no other signal, are not a BUY."""
    passes, fails, sig, _ = apply_callout_boost([], ["no independent signal"], None, handles, snap=snap, idx=idx)
    return would_buy(fails, sig), passes, fails, sig


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def try_refresh_official():
    """Best-effort public fetch. Returns (data_or_none, errors). Never raises for 403/502."""
    errors = []
    for url in OFFICIAL_TRY:
        try:
            return _get_json(url), errors
        except Exception as e:
            errors.append(f"{url}: {type(e).__name__}")
    # published snapshots (same field names as the official board)
    out = {}
    for period, url in SNAPSHOT_URLS.items():
        try:
            out[period] = _get_json(url)
        except Exception as e:
            errors.append(f"{url}: {type(e).__name__}")
    return (out or None), errors
