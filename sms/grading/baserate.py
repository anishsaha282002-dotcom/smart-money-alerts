"""How did past alerts of the same kind turn out? Read from data/baserates.json.

The file is written by `scripts/backtest_signals.py` from real wallet history and free price
candles. An alert is matched to the most specific bucket it belongs to (a 4-wallet cluster is
looked up as "cluster>=4/1h"). Buckets with fewer than MIN_SAMPLE signals are reported as
"not enough history" instead of a percentage. This is a measured past rate, never a forecast,
and never a reason given to buy or sell.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..backtest import MIN_SAMPLE
from ..config import ROOT

BASERATES_PATH = ROOT / "data" / "baserates.json"
LABEL = {
    "any-tracked-buy": "a single tracked wallet buying, no cluster",
    "kol-bought": "a single tracked KOL wallet buying, no cluster",
    "callout-leader-wallet-bought": "a Pump.fun Callout Rewards leader's wallet buying",
}


def load(path: str | Path | None = None) -> dict:
    p = Path(path or BASERATES_PATH)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def leader_wallets(snap: dict | None) -> set[str]:
    """Solana wallets of Pump.fun Callout Rewards leaders, from the leaderboard snapshot."""
    out = set()
    for row in (snap or {}).get("callers") or []:
        for w in [row.get("wallet"), *(row.get("wallets") or [])]:
            if w and not str(w).startswith("0x"):
                out.add(w)
    return out


def bucket_for(alert: dict, leaders: set[str] | None = None) -> str:
    cluster = alert.get("sm_cluster") or []
    k = len(cluster)
    if k >= 2:
        key = f"cluster>={min(k, 5)}/1h"
        if leaders and any(c.get("wallet") in leaders for c in cluster if isinstance(c, dict)):
            key += "+callout-leader"
        return key
    if alert.get("kol"):
        return "kol-bought"
    return "any-tracked-buy"


def label(key: str) -> str:
    if key.startswith("cluster>="):
        base, _, extra = key.partition("+")
        k, win = base[len("cluster>="):].split("/")
        tail = ", one of them a Pump.fun Callout Rewards leader" if extra else ""
        return f"{k}+ tracked wallets buying within {win}{tail}"
    return LABEL.get(key, key)


def lookup(alert: dict, rates: dict | None = None, horizon: str = "24h",
           leaders: set[str] | None = None) -> dict | None:
    rates = load() if rates is None else rates
    buckets = (rates or {}).get("buckets") or {}
    key = bucket_for(alert, leaders)
    if key not in buckets and "+" in key:
        key = key.split("+")[0]
    row = (buckets.get(key) or {}).get(horizon)
    if not row:
        return None
    return {"key": key, "label": label(key), "horizon": horizon, "period": rates.get("period", ""),
            "enough": row.get("n", 0) >= MIN_SAMPLE, **row}


def lines(br: dict | None) -> list[str]:
    if not br:
        return ["No backtest on file for this kind of alert yet."]
    if not br["enough"]:
        return [f"Not enough history yet: only {br['n']} past alerts of this kind ({br['label']}) were priced."]
    lo, hi = br.get("ci_2x") or (None, None)
    ci = f" (95% range {lo * 100:.0f}-{hi * 100:.0f}%)" if lo is not None else ""
    return [
        f"Of {br['n']} past alerts of this kind ({br['label']}, {br['period']}):",
        f"• {br['pct_2x'] * 100:.0f}% touched 2x within {br['horizon']}{ci}",
        f"• {br['pct_down50'] * 100:.0f}% fell 50% or more within {br['horizon']}",
        f"• median price after {br['horizon']}: {(br['median_x'] - 1) * 100:+.0f}%",
        "Past results of similar alerts, measured from the alert price. Not a forecast.",
    ]
