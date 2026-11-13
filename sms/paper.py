"""Paper trading: an imaginary bankroll follows the alerts under fixed rules. No real money, no wallet,
no orders. It reads the public record and minute candles and writes what *would* have happened to its
own append-only, hash-chained file (record/paper.jsonl), losses included.

Why it exists: the backtest picked wallets with hindsight. A paper run that starts today, with rules
fixed in advance, is the only honest test of whether a strategy has an edge.

The rules live in `PaperRules` and in config.toml [paper]. Change them, and the change is visible in the
file, because every opened position records the rules it was opened under.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .ledger import Ledger
from .models import Token

DAY = 86400


@dataclass
class PaperRules:
    start_sol: float = 1.0
    target_sol: float = 10.0
    risk_fraction: float = 0.15        # share of the bankroll put into one trade
    max_open: int = 3
    min_wallets: int = 3               # 3+ graded wallets: single buys and pairs lost money in the backtest
    grades: tuple = ("A", "B")
    narrative_states: tuple = ("new", "rising", "hot")
    min_still_held: float = 0.9        # skip if the wallet had already sold >10% before the alert
    max_mcap_usd: float = 3_000_000
    min_liquidity_usd: float = 20_000
    entry_slippage: float = 0.03       # paid on top of the alert-time price
    exit_slippage: float = 0.03
    fee: float = 0.01                  # per side
    stop_loss: float = 0.65            # exit if price falls to 65% of entry
    take_half_at: float = 2.0          # sell half at 2x
    trail_after_half: float = 0.70     # then exit the rest 30% below the highest price since
    moon_at: float = 6.0               # sell the rest at 6x
    max_hold_s: int = DAY


def eligible(alert: dict, r: PaperRules) -> tuple[bool, str]:
    """Would the strategy take this alert? Returns (yes/no, reason)."""
    if alert.get("demo"):
        return False, "demo data"
    if (alert.get("activity") or "sm_buying") not in ("sm_buying", "buy"):
        return False, "not a buy"
    w = alert["grades"]["wallet"]
    if w.get("grade") not in r.grades:
        return False, f"wallet grade {w.get('grade')}"
    wallets = 1 + len(alert.get("cluster") or alert.get("sm_cluster") or [])
    if wallets < r.min_wallets:
        return False, f"only {wallets} wallet"
    state = alert["grades"]["narrative"].get("state")
    if state not in r.narrative_states:
        return False, f"narrative {state}"
    held = (alert.get("holding") or {}).get("held")
    if held is not None and held < r.min_still_held:
        return False, f"wallet already sold {round((1 - held) * 100)}%"
    if (alert.get("mcap_usd") or 0) > r.max_mcap_usd:
        return False, "market cap too big for a 10x"
    if (alert.get("liquidity_usd") or 0) < r.min_liquidity_usd:
        return False, "too little liquidity to get out"
    risks = " ".join((alert.get("safety") or {}).get("risks") or []).lower()
    if any(k in risks for k in ("honeypot", "sell tax", "cannot sell", "rugged")):
        return False, "safety warning"
    if not alert.get("entry_price"):
        return False, "no price"
    return True, "ok"


def simulate_exit(candles: list[list], entry_px: float, opened: int, r: PaperRules, now: int) -> dict | None:
    """Walk minute candles after entry. Returns the exit (or None while still open).

    The value is a multiple of the SOL put in, after fees and slippage on every sale.
    """
    sold, value, peak = 0.0, 0.0, entry_px
    half_taken = False
    for ts, _o, hi, lo, cl, _v in candles:
        if ts <= opened:
            continue
        if not half_taken and lo <= entry_px * r.stop_loss:
            value += (1 - sold) * r.stop_loss * (1 - r.exit_slippage) * (1 - r.fee)
            return {"ts": ts, "x": round(value, 4), "why": "stop loss"}
        if not half_taken and hi >= entry_px * r.take_half_at:
            value += 0.5 * r.take_half_at * (1 - r.exit_slippage) * (1 - r.fee)
            sold, half_taken = 0.5, True
            peak = max(peak, hi)
            continue        # a candle's high and low have no known order: start trailing from the next one
        peak = max(peak, hi)
        if half_taken and hi >= entry_px * r.moon_at:
            value += (1 - sold) * r.moon_at * (1 - r.exit_slippage) * (1 - r.fee)
            return {"ts": ts, "x": round(value, 4), "why": f"took the rest at {r.moon_at:g}x"}
        if half_taken and lo <= peak * r.trail_after_half:
            px = max(peak * r.trail_after_half, lo) / entry_px
            value += (1 - sold) * px * (1 - r.exit_slippage) * (1 - r.fee)
            return {"ts": ts, "x": round(value, 4), "why": "trailing stop after taking half"}
        if ts - opened >= r.max_hold_s:
            value += (1 - sold) * (cl / entry_px) * (1 - r.exit_slippage) * (1 - r.fee)
            return {"ts": ts, "x": round(value, 4), "why": "24h time limit"}
    if now - opened > r.max_hold_s + 6 * 3600 and not candles:
        return {"ts": now, "x": round(value, 4), "why": "no price data: counted as lost"}
    if now - opened > r.max_hold_s + 6 * 3600:
        last = candles[-1][4] / entry_px
        value += (1 - sold) * last * (1 - r.exit_slippage) * (1 - r.fee)
        return {"ts": now, "x": round(value, 4), "why": "price data stopped: closed at last price"}
    return None


def state(book: Ledger, r: PaperRules) -> dict:
    """Bankroll and open positions, rebuilt from the paper file."""
    bank, open_, closed = r.start_sol, {}, []
    for e in book.entries():
        if e["type"] == "paper_open":
            bank -= e["size_sol"]
            open_[e["alert_id"]] = e
        elif e["type"] == "paper_close":
            bank += e["back_sol"]
            closed.append(e)
            open_.pop(e["alert_id"], None)
    seen = {e["alert_id"] for e in book.entries() if e["type"] in ("paper_open", "paper_skip")}
    return {"cash": round(bank, 6), "open": open_, "closed": closed, "seen": seen}


def step(hub, alerts_ledger: Ledger, book: Ledger, r: PaperRules | None = None) -> dict:
    """One pass: close what can be closed, then open what qualifies. Idempotent."""
    r = r or PaperRules()
    now = hub.now()
    st = state(book, r)
    for aid, pos in list(st["open"].items()):
        tok = Token(chain="solana", address=pos["token"], pool=pos.get("pool") or "")
        candles = hub.candles("solana", tok, pos["ts"] - 60, min(now, pos["ts"] + r.max_hold_s + 600))
        ex = simulate_exit(candles, pos["entry_px"], pos["ts"], r, now)
        if ex:
            back = round(pos["size_sol"] * ex["x"], 6)
            book.append("paper_close", now, {"alert_id": aid, "symbol": pos["symbol"], "exit_ts": ex["ts"],
                                             "x": ex["x"], "why": ex["why"], "back_sol": back,
                                             "pnl_sol": round(back - pos["size_sol"], 6)})
            st["cash"] += back
            st["open"].pop(aid)
    equity = st["cash"] + sum(p["size_sol"] for p in st["open"].values())
    for a in alerts_ledger.entries("alert"):
        if a["id"] in st["seen"] or now - a["ts"] > 2 * 3600:
            continue
        ok, why = eligible(a, r)
        if ok and len(st["open"]) >= r.max_open:
            ok, why = False, "already holding the maximum number of positions"
        if ok and equity < 0.05:
            ok, why = False, "bankroll gone"
        if not ok:
            book.append("paper_skip", now, {"alert_id": a["id"], "why": why})
            continue
        size = round(min(st["cash"], equity * r.risk_fraction) * (1 - r.fee), 6)
        entry = a["entry_price"] * (1 + r.entry_slippage)
        book.append("paper_open", now, {"alert_id": a["id"], "token": a["token"]["address"],
                                        "symbol": a["token"].get("symbol") or "", "pool": a["token"].get("pool") or "",
                                        "entry_px": entry, "size_sol": size, "rules": asdict(r)})
        st["cash"] -= size
        st["open"][a["id"]] = {"ts": now, "size_sol": size}
    return summary(book, r)


def summary(book: Ledger, r: PaperRules) -> dict:
    st = state(book, r)
    closed = st["closed"]
    in_open = sum(p["size_sol"] for p in st["open"].values())
    wins = [c for c in closed if c["pnl_sol"] > 0]
    return {"start_sol": r.start_sol, "target_sol": r.target_sol, "cash_sol": round(st["cash"], 4),
            "in_positions_sol": round(in_open, 4), "equity_sol": round(st["cash"] + in_open, 4),
            "trades": len(closed), "wins": len(wins), "open": len(st["open"]),
            "skipped": sum(1 for e in book.entries() if e["type"] == "paper_skip"),
            "best_x": max((c["x"] for c in closed), default=None),
            "worst_x": min((c["x"] for c in closed), default=None),
            "head": book.head}


def text(s: dict) -> str:
    lines = [f"PAPER RUN (imaginary money, no real trades): {s['start_sol']:g} SOL -> target {s['target_sol']:g} SOL",
             f"Now: {s['equity_sol']:.3f} SOL ({s['cash_sol']:.3f} cash + {s['in_positions_sol']:.3f} in {s['open']} open)",
             f"Closed trades: {s['trades']}, won {s['wins']}. Skipped alerts: {s['skipped']}."]
    if s["trades"]:
        lines.append(f"Best trade {s['best_x']:.2f}x, worst {s['worst_x']:.2f}x of the SOL put in.")
    lines.append(f"Paper file head hash {s['head']}")
    return "\n".join(lines)
