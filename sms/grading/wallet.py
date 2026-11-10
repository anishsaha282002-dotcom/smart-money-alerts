"""Wallet grade (A–D) from closed trades. Deterministic: same trades in, same grade out.

What goes in, out of 100:

    win rate        40   shrunk toward 50% by sample size, so 4 wins from 4 is not "100%"
    return on cost  30   realised profit / money put in, shrunk the same way (full marks: doubled it)
    spread          20   how much of the profit does NOT rest on one trade
    hold time       10   seconds-long holds are a machine, not a judgement to follow

    minus penalties      bot, wash trading, sniper, bundle, fresh-funded cluster, insider tag

    A ≥ 75   B ≥ 50   C ≥ 35   D below

Three choices worth knowing about:

* Only *closed* trades count (≥90% of what was bought has been sold). Paper gains are not a record.
* A position bought more than `stale_days` ago and never sold is counted as a full loss. Without
  this a wallet that only ever sells its winners and lets the rest rot would look perfect.
* With fewer than `cap_below` closed trades the grade cannot be better than C, whatever the score.
  The same cap applies to a wallet flagged as a bot, wash trader, bundler, insider or fresh cluster.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from ..models import Trade, WalletGrade

FRESH_SECONDS = 3 * 86400       # younger than this is a "fresh" wallet (threshold after crawl-hive)
SNIPE_SECONDS = 2               # bought within this of the token's creation
PENALTIES = {"bot": 30, "wash": 30, "bundle": 20, "fresh-cluster": 20, "insider": 20, "sniper": 15, "fresh": 10}
SERIOUS = {"bot", "wash", "bundle", "fresh-cluster", "insider"}     # never better than C, whatever the score
FLAG_TEXT = {
    "bot": "trades like a bot (holds for seconds or fires hundreds of trades a day)",
    "wash": "wash-trading pattern (fast round trips that go nowhere)",
    "bundle": "takes part in bundled launches",
    "fresh-cluster": "new wallet funded from the same source as other buyers",
    "insider": "tagged as an insider / rat trader by the data source",
    "sniper": "snipes launches in the first seconds",
    "fresh": "wallet is only days old",
    "one-hit": "most of its profit comes from a single trade",
}
THRESHOLDS = (("A", 75), ("B", 50), ("C", 35))


@dataclass
class Closed:
    token: str
    symbol: str
    cost: float
    proceeds: float
    opened: int
    closed: int
    abandoned: bool = False

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost

    @property
    def roi(self) -> float:
        return self.pnl / self.cost if self.cost > 0 else 0.0

    @property
    def hold(self) -> int:
        return max(0, self.closed - self.opened)


def close_trades(trades: list[Trade], now: int, days: int = 30, stale_days: int = 7) -> list[Closed]:
    """Pair buys with sells per token into closed round trips inside the window."""
    since = now - days * 86400
    by_token: dict[tuple, list[Trade]] = {}
    for t in trades:
        if t.ts <= now:
            by_token.setdefault((t.chain, t.token), []).append(t)

    out: list[Closed] = []
    for (_, token), ts in by_token.items():
        ts.sort(key=lambda t: (t.ts, t.side != "buy"))
        b_tok = b_usd = s_tok = s_usd = 0.0
        opened = last_sell = None
        symbol = next((t.symbol for t in ts if t.symbol), "")
        for t in ts:
            if t.side == "buy":
                if opened is None:
                    opened = t.ts
                b_tok += t.token_amount
                b_usd += t.usd
            elif opened is not None:          # a sell with no buy in view has no known cost: skipped
                s_tok += t.token_amount
                s_usd += t.usd
                last_sell = t.ts
                # token amounts when the source has them, dollars as a stand-in when it does not
                done = s_tok >= 0.9 * b_tok if b_tok > 0 and s_tok > 0 else s_usd >= 0.9 * b_usd
                if done:
                    if t.ts >= since:
                        out.append(Closed(token, symbol, b_usd, s_usd, opened, t.ts))
                    b_tok = b_usd = s_tok = s_usd = 0.0
                    opened = last_sell = None
        if opened is not None and b_usd > 0:
            # still open. Partly sold and then left alone for a day: closed at what came back.
            if last_sell is not None and now - last_sell > 86400 and last_sell >= since:
                out.append(Closed(token, symbol, b_usd, s_usd, opened, last_sell))
            # never sold and old: a bag. Counted as lost, on the day it went stale.
            elif last_sell is None and now - opened > stale_days * 86400 and opened + stale_days * 86400 >= since:
                out.append(Closed(token, symbol, b_usd, 0.0, opened, opened + stale_days * 86400, abandoned=True))
    # a round trip with no dollar value on either side (a source that reports token amounts only)
    # says nothing about skill: leave it out instead of counting it as a $0 loss
    out = [c for c in out if c.cost > 0 or c.proceeds > 0]
    out.sort(key=lambda c: c.closed)
    return out


def shrink_rate(wins: int, n: int, prior: int = 10) -> float:
    """Win rate pulled toward 50% as if `prior` extra coin-flip trades had been seen."""
    return (wins + prior / 2) / (n + prior)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def detect_flags(trades: list[Trade], closed: list[Closed], now: int, meta: dict | None, days: int) -> list[str]:
    meta = meta or {}
    tags = {str(t).lower() for t in meta.get("tags") or []}
    flags: list[str] = []
    window = [t for t in trades if now - days * 86400 <= t.ts <= now]
    buys = [t for t in window if t.side == "buy"]
    real = [c for c in closed if not c.abandoned]

    span_days = max(1.0, (max((t.ts for t in window), default=now) - min((t.ts for t in window), default=now)) / 86400)
    holds = [c.hold for c in real]
    # identical buy sizes are NOT used as a bot signal: plenty of people always buy "1 SOL"
    if (len(holds) >= 5 and statistics.median(holds) < 60) or len(window) / span_days > 150 or "bot" in tags:
        flags.append("bot")

    if len(real) >= 5 and sum(abs(c.roi) < 0.02 and c.hold < 300 for c in real) / len(real) >= 0.4:
        flags.append("wash")

    timed = [t for t in buys if t.token_created_ts]
    sniped = sum(0 <= t.ts - t.token_created_ts <= SNIPE_SECONDS for t in timed)
    if (len(timed) >= 3 and sniped / len(timed) >= 0.5) or "sniper" in tags:
        flags.append("sniper")

    if "bundler" in tags or "bundle" in tags or (meta.get("bundled_buys") or 0) >= 3:
        flags.append("bundle")
    if tags & {"rat_trader", "insider", "rat"}:
        flags.append("insider")

    funded = meta.get("first_funded_ts")
    if funded and now - funded < FRESH_SECONDS:
        flags.append("fresh-cluster" if (meta.get("cluster_size") or 0) >= 2 else "fresh")

    wins = sorted((c.pnl for c in closed if c.pnl > 0), reverse=True)
    if wins and len(closed) >= 3 and wins[0] / sum(wins) > 0.8:
        flags.append("one-hit")
    return flags


def grade_wallet(trades: list[Trade], now: int, meta: dict | None = None, *, days: int = 30,
                 prior: int = 10, small_sample: int = 10, cap_below: int = 5) -> WalletGrade:
    closed = close_trades(trades, now, days)
    n = len(closed)
    wins = sum(c.pnl > 0 for c in closed)
    cost = sum(c.cost for c in closed)
    pnl = sum(c.pnl for c in closed)
    roi = pnl / cost if cost > 0 else None
    holds = [c.hold for c in closed if not c.abandoned]
    median_hold = statistics.median(holds) if holds else None
    last10 = closed[-10:]
    buys = [t.usd for t in trades if t.side == "buy" and now - days * 86400 <= t.ts <= now and t.usd > 0]

    wr_s = shrink_rate(wins, n, prior)
    weight = n / (n + prior)                      # how much the sample is trusted, 0..1
    roi_s = (roi or 0.0) * weight
    positive = sorted((c.pnl for c in closed if c.pnl > 0), reverse=True)
    top_share = positive[0] / sum(positive) if len(positive) >= 2 else 1.0

    parts = {
        "win_rate": round(40 * _clamp((wr_s - 0.40) / 0.30), 1),
        "return": round(30 * _clamp(roi_s / 1.00), 1),
        "spread": round(20 * _clamp((1 - top_share - 0.10) / 0.60), 1) if n else 0.0,
        "hold": round(10 * _clamp((math.log10(max(median_hold, 1)) - math.log10(60)) / (math.log10(1800) - math.log10(60))), 1)
                if median_hold is not None else 0.0,
    }
    flags = detect_flags(trades, closed, now, meta, days)
    penalties = {f: PENALTIES[f] for f in flags if f in PENALTIES}
    score = int(round(max(0.0, min(100.0, sum(parts.values()) - sum(penalties.values())))))

    grade = next((g for g, floor in THRESHOLDS if score >= floor), "D")
    capped = False
    if (n < cap_below or SERIOUS & set(flags)) and grade in ("A", "B"):
        grade, capped = "C", True

    return WalletGrade(
        grade=grade, score=score, n_closed=n, wins=wins,
        last10_wins=sum(c.pnl > 0 for c in last10), last10_n=len(last10),
        win_rate=round(wins / n, 3) if n else None, win_rate_shrunk=round(wr_s, 3),
        pnl_usd=round(pnl, 2), roi=round(roi, 3) if roi is not None else None,
        median_hold_s=median_hold, flags=flags, penalties=penalties, parts=parts,
        small_sample=n < small_sample, capped=capped, days=days,
        median_buy_usd=round(statistics.median(buys), 2) if buys else None,
        n_tokens=len({c.token for c in closed}), wins_tokens=len({c.token for c in closed if c.pnl > 0}),
    )
