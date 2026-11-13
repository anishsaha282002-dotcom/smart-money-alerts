"""How likely is 1 SOL -> 10 SOL? A Monte Carlo from the measured base rates in data/baserates.json.

Each trade's outcome is drawn from what alerts of that kind actually did over 24h in the backtest:
  * touched 2x before -50%  -> half sold at 2x, the rest exits on a 30% trailing stop (modelled as
                               1.3x-6x, mostly low end), net of fees and slippage
  * fell to the stop first  -> 0.65x of entry, minus slippage and fees
  * neither                 -> the bucket's median 24h close
These buckets come from wallets picked with hindsight over 3 days, so real odds are likely worse.
Run:  python scripts/paper_odds.py
"""
from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

COST = 0.97 * 0.99  # exit slippage and fee
BUCKETS = ("any-tracked-buy", "cluster>=2/1h", "cluster>=3/1h", "cluster>=5/30m", "cluster>=3/6h+callout-leader")


def outcome(b: dict, rng: random.Random) -> float:
    d = b["24h"]
    p_win = b["pct_2x_before_down50_24h"]
    p_stop = max(0.0, d["pct_down50"] - (d["pct_2x"] - p_win)) * 1.15   # the 35% stop triggers before -50%
    u = rng.random()
    if u < p_win:
        rest = rng.choice([1.3, 1.4, 1.5, 1.7, 2.0, 2.5, 3.5, 6.0])     # trailing stop, skewed low
        return (0.5 * 2.0 + 0.5 * rest) * COST
    if u < p_win + p_stop:
        return 0.65 * COST
    return d["median_x"] * COST


def run(b: dict, trades_cap: int = 300, risk: float = 0.15, seed: int = 0, runs: int = 20000):
    rng = random.Random(seed)
    hit = bust = 0
    finals, trades_to_10 = [], []
    for _ in range(runs):
        bank = 1.0
        for n in range(1, trades_cap + 1):
            stake = bank * risk * 0.99
            bank += stake * (outcome(b, rng) - 1)
            if bank >= 10:
                hit += 1
                trades_to_10.append(n)
                break
            if bank < 0.05:
                bust += 1
                break
        finals.append(bank)
    return {"p10": hit / runs, "p_bust": bust / runs, "median_final": statistics.median(finals),
            "median_trades_to_10": statistics.median(trades_to_10) if trades_to_10 else None}


def ev(b: dict, rng=random.Random(1), n=200000) -> float:
    return sum(outcome(b, rng) for _ in range(n)) / n


if __name__ == "__main__":
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "baserates.json").read_text())
    print(f"Base rates: {data['period']} ({data['signals']} signals)\n")
    print(f"{'signal':30} {'n':>4} {'avg per trade':>14} {'P(reach 10 SOL)':>16} {'P(bust)':>8} {'median end':>11}")
    for name in BUCKETS:
        b = data["buckets"].get(name)
        if not b:
            continue
        r = run(b)
        print(f"{name:30} {b['24h']['n']:>4} {ev(b) - 1:>+13.1%} {r['p10']:>15.2%} {r['p_bust']:>8.1%} {r['median_final']:>10.3f}")
