"""Wallet grade A-D from closed-trade results.

Method (documented in README "How grades work"; inspired by the public write-ups of
Stable Boy and MadeOnSol - we do not claim to reproduce them exactly):

1. Rebuild positions per token from the wallet's buys/sells (no transfers). A position
   opens on the first buy from flat and is *closed* once >= closed_fraction of its peak
   size has been sold. Return = proceeds / cost - 1 in the trade's own unit (USD or SOL/BNB).
2. Only closed positions inside the window count. Open bags are ignored, which is what
   keeps "unrealized moonbag" wallets from looking better than they are.
3. Win rate is shrunk toward 50% with k pseudo-trades: (wins + k/2) / (n + k). A wallet
   that is 3/3 gets 0.64, not 1.0.
4. Score (0-100) = 50 + 50 * (0.5*win_edge + 0.3*tanh(median_return/0.5) + 0.2*tanh(ln(profit_factor)))
   minus penalties: bot-like (-25), wash-like (-20), bundle/sniper-like (-15).
5. A >= 75, B >= 62, C >= 50, else D. n < low_sample caps the grade at C with a LOW SAMPLE
   warning; n < min_closed_trades is U (ungraded) and never alerts.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, asdict

from ..util import median, fnum


@dataclass
class Position:
    token: str
    chain: str
    open_ts: int
    close_ts: int | None
    cost: float
    proceeds: float
    unit: str
    first_buy_price_usd: float | None
    n_buys: int
    n_sells: int
    peak_amount: float
    symbol: str = ""
    token_created_ts: int | None = None
    first_buy_tx: str = ""

    @property
    def closed(self):
        return self.close_ts is not None

    @property
    def ret(self):
        return self.proceeds / self.cost - 1 if self.cost > 0 else None

    @property
    def hold_s(self):
        return (self.close_ts - self.open_ts) if self.close_ts else None


@dataclass
class WalletGrade:
    wallet: str
    chain: str
    grade: str
    score: float
    n_closed: int
    wins: int
    win_rate_raw: float | None
    win_rate_shrunk: float | None
    median_return: float | None
    profit_factor: float | None
    median_hold_s: float | None
    last10_wins: int
    last10_n: int
    window_days: int
    flags: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    n_open: int = 0
    trades_seen: int = 0
    data_source: str = ""
    coverage_h: float | None = None

    def record_phrase(self):
        if self.n_closed == 0:
            return f"no closed trades in the last {self.window_days}d"
        return (f"won {self.last10_wins} of last {self.last10_n} closed trades over {self.window_days}d"
                + (f" ({self.wins}/{self.n_closed} overall)" if self.n_closed > self.last10_n else ""))

    def to_dict(self):
        return asdict(self)


def build_positions(trades, closed_fraction=0.9):
    by_tok = defaultdict(list)
    for t in trades:
        by_tok[(t["chain"], t["token"])].append(t)
    out = []
    for (chain, tok), ts in by_tok.items():
        ts.sort(key=lambda x: (x["ts"], 0 if x["side"] == "buy" else 1))
        cur = None
        held = 0.0
        for t in ts:
            amt = fnum(t.get("token_amount"))
            val = fnum(t.get("value"))
            if cur is not None and t.get("value_unit", "usd") != cur.unit:
                continue          # mixed quote units inside one position (e.g. SOL buy, USDC sell): skip leg
            if t["side"] == "buy":
                if cur is None:
                    cur = Position(tok, chain, int(t["ts"]), None, 0.0, 0.0, t.get("value_unit", "usd"),
                                   t.get("price_usd"), 0, 0, 0.0, t.get("symbol", ""), t.get("token_created_ts"),
                                   t.get("tx", ""))
                    if cur.first_buy_price_usd is None and t.get("value_unit") == "usd" and amt > 0:
                        cur.first_buy_price_usd = val / amt
                cur.cost += val
                cur.n_buys += 1
                held += amt
                cur.peak_amount = max(cur.peak_amount, held)
            else:
                if cur is None or held <= 0:
                    continue          # sell of tokens we never saw bought (airdrop/transfer): ignore
                sold = min(amt, held) if amt > 0 else held
                frac = sold / amt if amt > 0 else 1.0
                cur.proceeds += val * frac
                cur.n_sells += 1
                held -= sold
                if held <= (1 - closed_fraction) * cur.peak_amount:
                    cur.close_ts = int(t["ts"])
                    out.append(cur)
                    cur, held = None, 0.0
        if cur is not None:
            out.append(cur)
    return out


def _flags(positions, trades):
    flags = []
    closed = [p for p in positions if p.closed]
    holds = [p.hold_s for p in closed if p.hold_s is not None]
    mh = median(holds)
    days = max(1.0, (max(t["ts"] for t in trades) - min(t["ts"] for t in trades)) / 86400) if trades else 1
    per_day = len(trades) / days
    if (mh is not None and mh < 30 and len(closed) >= 5) or per_day > 300:
        flags.append("bot-like")        # sub-30s median holds or >300 trades/day: not copyable by a human
    rt = [p for p in closed if p.hold_s is not None and p.hold_s < 120 and p.ret is not None and abs(p.ret) < 0.02]
    if len(closed) >= 5 and len(rt) / len(closed) >= 0.3:
        flags.append("wash-like")       # many flat round-trips: volume farming, not conviction
    snipes = [p for p in positions if p.token_created_ts and 0 <= p.open_ts - p.token_created_ts <= 5]
    if len(positions) >= 5 and len(snipes) / len(positions) >= 0.5:
        flags.append("bundle/sniper-like")   # buys in the launch block: you cannot get that price
    return flags


PENALTY = {"bot-like": 25, "wash-like": 20, "bundle/sniper-like": 15}


def grade_wallet(wallet, chain, trades, now_ts, *, window_days=30, shrink_k=8, low_sample=5, small_sample=10,
                 min_closed=3, closed_fraction=0.9, data_source=""):
    trades = [t for t in trades if t.get("ts")]
    positions = build_positions(trades, closed_fraction)
    since = now_ts - window_days * 86400
    closed = sorted([p for p in positions if p.closed and p.close_ts >= since and p.ret is not None],
                    key=lambda p: p.close_ts, reverse=True)
    n = len(closed)
    wins = sum(1 for p in closed if p.ret > 0)
    last10 = closed[:10]
    rets = [p.ret for p in closed]
    gains = sum(p.proceeds - p.cost for p in closed if p.ret > 0)
    losses = -sum(p.proceeds - p.cost for p in closed if p.ret <= 0)
    pf = (gains / losses) if losses > 0 else (float("inf") if gains > 0 else None)
    flags = _flags(positions, trades)
    warnings = []
    wr_raw = wins / n if n else None
    wr_s = (wins + shrink_k * 0.5) / (n + shrink_k) if n else None
    med = median(rets)
    if n < min_closed:
        grade, score = "U", 0.0
        warnings.append(f"UNGRADED: only {n} closed trade(s) in {window_days}d (need {min_closed})")
    else:
        edge = (wr_s - 0.5) * 2
        pfc = math.tanh(math.log(pf)) if pf not in (None, float("inf")) and pf > 0 else (1.0 if pf == float("inf") else -1.0)
        score = 50 + 50 * (0.5 * edge + 0.3 * math.tanh((med or 0) / 0.5) + 0.2 * pfc)
        score -= sum(PENALTY[f] for f in flags)
        score = max(0.0, min(100.0, score))
        grade = "A" if score >= 75 else "B" if score >= 62 else "C" if score >= 50 else "D"
        if n < low_sample:
            warnings.append(f"LOW SAMPLE: only {n} closed trades - grade capped at C; treat it as a guess")
            if grade in ("A", "B"):
                grade = "C"
        elif n < small_sample:
            warnings.append(f"small sample: {n} closed trades - the grade can move a lot")
    cov = (max(t["ts"] for t in trades) - min(t["ts"] for t in trades)) / 3600 if trades else 0.0
    if trades and cov < window_days * 24 * 0.25:
        warnings.append(f"history covers only {cov:.1f}h of the {window_days}d window (source: {data_source or 'n/a'}) - "
                        "record is partial")
    return WalletGrade(wallet, chain, grade, round(score, 1), n, wins, wr_raw, wr_s, med,
                       None if pf is None else (round(pf, 2) if pf != float("inf") else 999.0),
                       median([p.hold_s for p in closed]), sum(1 for p in last10 if p.ret > 0), len(last10),
                       window_days, flags, warnings, sum(1 for p in positions if not p.closed), len(trades),
                       data_source, round(cov, 1)), positions
