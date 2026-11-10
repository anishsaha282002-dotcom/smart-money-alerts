"""Replay every signal type on past wallet history and write data/baserates.json.

Inputs (all free): a SQLite file with
  swaps(sig, wallet, mint, side, tok, sol, usd_q, ts)   tracked-wallet swaps (see scripts/backtest_crawl.py)
  ohlcv(mint, ts, o, h, l, c, v)                        5-minute USD candles from GeckoTerminal
  wdone(wallet, n, capped)                              optional: wallets whose history was capped (bot-like)
Output: data/baserates.json with, per signal bucket and horizon, n / % touched 2x / % fell 50% /
median and mean multiple / 95% interval, plus how many signals could not be priced.

Usage: python scripts/backtest_signals.py --db bt.db [--now 1794304000] [--out data/baserates.json]
History, not a forecast. Nothing here ever buys or sells.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sms import backtest as bt  # noqa: E402
from sms.wallets import bot_reason  # noqa: E402

WINDOWS = {"30m": 1800, "1h": 3600, "6h": 6 * 3600}
SIZES = (2, 3, 4, 5)


def load_book(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {w["address"]: w for w in data.get("wallets") or [] if w.get("address")}


def leaderboard_wallets(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {w for c in data.get("callers") or [] for w in [c.get("wallet"), *(c.get("wallets") or [])] if w}


def units(first: dict) -> list[dict]:
    """First buys per wallet, with buys in the same second or same transaction merged (bundle-like)."""
    out = []
    for w, (ts, sig) in sorted(first.items(), key=lambda kv: kv[1][0]):
        if out and (out[-1]["ts"] == ts or sig in out[-1]["sigs"]):
            out[-1]["w"].append(w)
            out[-1]["sigs"].add(sig)
            out[-1]["bundled"] = True
            continue
        out.append({"ts": ts, "w": [w], "sigs": {sig}, "bundled": False})
    return out


def cluster_time(us: list[dict], k: int, win: int) -> tuple[int, list[str]] | None:
    for i in range(len(us)):
        j = i + k - 1
        if j < len(us) and us[j]["ts"] - us[i]["ts"] <= win:
            return us[j]["ts"], [w for u in us[i:j + 1] for w in u["w"]]
    return None


def build_signals(db, book: dict, lbw: set[str], since: int = 0) -> tuple[list[dict], dict]:
    capped = set()
    try:
        capped = {r[0] for r in db.execute("select wallet from wdone where capped=1")}
    except sqlite3.OperationalError:
        pass
    excluded = {w: "history capped: thousands of transactions a day" for w in capped}
    for w, row in book.items():
        r = bot_reason(row)
        if r:
            excluded[w] = r
    first: dict[str, dict] = collections.defaultdict(dict)
    for sig, w, m, ts in db.execute("select sig, wallet, mint, ts from swaps where side='buy' and ts >= ? order by ts",
                                    (since,)):
        if w in excluded:
            continue
        first[m].setdefault(w, (ts, sig))
    sigs = []
    for m, f in first.items():
        us = units(f)
        for k in SIZES:
            for lab, win in WINDOWS.items():
                c = cluster_time(us, k, win)
                if c:
                    sigs.append({"type": f"cluster>={k}/{lab}", "mint": m, "ts": c[0], "wallets": c[1],
                                 "lb": any(w in lbw for w in c[1])})
        ev = sorted(f.items(), key=lambda kv: kv[1][0])
        kol = [x for x in ev if "kol" in (book.get(x[0], {}).get("tags") or [])]
        if kol:
            sigs.append({"type": "kol-bought", "mint": m, "ts": kol[0][1][0], "wallets": [kol[0][0]], "lb": False})
        lb = [x for x in ev if x[0] in lbw]
        if lb:
            sigs.append({"type": "callout-leader-wallet-bought", "mint": m, "ts": lb[0][1][0],
                         "wallets": [lb[0][0]], "lb": True})
        sigs.append({"type": "any-tracked-buy", "mint": m, "ts": ev[0][1][0], "wallets": [ev[0][0]], "lb": False})
    return sigs, excluded


def score(db, sigs: list[dict], now: int, priced_mints: set[str] | None = None,
          baseline: set[str] | None = None) -> dict:
    """baseline: mints of a random sample of non-cluster buys. When given, the single-wallet
    buckets (any tracked buy, KOL bought, callout leader bought) are scored on it only, because
    the cluster mints were priced first and would bias those buckets."""
    candles: dict[str, list] = collections.defaultdict(list)
    for m, ts, o, h, lo, c in db.execute("select mint, ts, o, h, l, c from ohlcv order by ts"):
        candles[m].append([ts, o, h, lo, c])
    buckets: dict[str, dict] = {}
    by_type = collections.defaultdict(list)
    for s in sigs:
        if priced_mints is not None and s["mint"] not in priced_mints:
            continue
        if baseline is not None and not s["type"].startswith("cluster>=") and s["mint"] not in baseline:
            continue
        by_type[s["type"]].append(s)
        if s["type"].startswith("cluster>=") and s.get("lb"):
            by_type[s["type"] + "+callout-leader"].append(s)
    for typ, group in sorted(by_type.items()):
        results, unpriced, order = [], 0, collections.Counter()
        for s in group:
            f = bt.forward(candles.get(s["mint"], []), s["ts"], now)
            if f is None:
                unpriced += 1
                continue
            results.append(f)
            if f.get("24h"):
                order[bt.two_x_before_half(candles[s["mint"]], s["ts"], 86400)] += 1
        row = {"signals": len(group), "unpriced": unpriced}
        for h in bt.FWD_HORIZONS:
            sm = bt.summarize(results, h)
            if sm["n"]:
                sm["ci_2x"] = list(bt.wilson(round(sm["pct_2x"] * sm["n"]), sm["n"]))
                dd = [bt.max_drawdown(candles[s["mint"]], s["ts"], bt.FWD_HORIZONS[h]) for s in group
                      if candles.get(s["mint"]) and bt.entry_candle(candles[s["mint"]], s["ts"])
                      and now >= s["ts"] + bt.FWD_HORIZONS[h]]
                dd = [d for d in dd if d is not None]
                sm["median_max_drawdown"] = round(statistics.median(dd), 4) if dd else None
            row[h] = sm
        n24 = sum(order.values())
        row["pct_2x_before_down50_24h"] = round(order[True] / n24, 4) if n24 else None
        buckets[typ] = row
    return buckets


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--wallets", default=str(ROOT / "data" / "smart_wallets.json"))
    ap.add_argument("--leaderboard", default=str(ROOT / "data" / "pumpfun_callout_leaderboard.json"))
    ap.add_argument("--now", type=int, default=None, help="end of the data (unix); default: newest swap")
    ap.add_argument("--priced-only", action="store_true", help="only score mints that have a candle table entry")
    ap.add_argument("--since", type=int, default=0, help="ignore swaps before this unix time (full-coverage start)")
    ap.add_argument("--baseline", default=None, help="JSON list of random non-cluster mints for single-wallet buckets")
    ap.add_argument("--delay", type=int, default=0, help="seconds between signal and entry (copy-lag test)")
    ap.add_argument("--out", default=str(ROOT / "data" / "baserates.json"))
    a = ap.parse_args(argv)
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    book = load_book(Path(a.wallets))
    sigs, excluded = build_signals(db, book, leaderboard_wallets(Path(a.leaderboard)), a.since)
    lo, hi = db.execute("select min(ts), max(ts) from swaps where ts >= ?", (a.since,)).fetchone()
    now = a.now or hi
    priced = None
    if a.priced_only:
        priced = {r[0] for r in db.execute("select mint from ohlcv_done")}
    if a.delay:
        for s in sigs:
            s["ts"] += a.delay
    base = set(json.loads(Path(a.baseline).read_text())) if a.baseline else None
    buckets = score(db, sigs, now, priced, base)
    day = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d %b %Y")  # noqa: E731
    out = {
        "generated_ts": now, "period": f"signals {day(lo)} to {day(hi)} UTC", "min_sample": bt.MIN_SAMPLE,
        "method": ("Entry = close of the 5-minute candle containing the signal (not the wallet's fill). "
                   "2x uses candle highs and -50% candle lows inside the window. Bot-like wallets excluded; "
                   "buys by several tracked wallets in the same second or transaction count once."),
        "entry_delay_s": a.delay, "excluded_wallets": len(excluded), "signals": len(sigs), "buckets": buckets,
    }
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "buckets"}))
    for k, v in buckets.items():
        r = v.get("24h") or {}
        print(f"{k:42} signals={v['signals']:5} unpriced={v['unpriced']:4} n24={r.get('n', 0):4} "
              f"2x={r.get('pct_2x')} -50%={r.get('pct_down50')} med={r.get('median_x')}")


if __name__ == "__main__":
    main()
