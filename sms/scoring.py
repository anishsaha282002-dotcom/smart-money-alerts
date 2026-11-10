"""Go back to old alerts and write down what happened: +15m, +1h, +4h, +24h, and the copy check.

Every result is a new ledger line pointing at the alert. Nothing is filtered: a coin that went
to zero gets its line like any other. Three kinds of result exist besides a normal price:

    quiet     nobody traded in the hour before the checkpoint. The last traded price is recorded,
              but you could not have sold there, so reports count these as misses.
    no_data   no candles at all, six hours past the checkpoint. Recorded so it cannot be retried
              until a flattering number turns up.
    pending   not due yet: simply no line.

All multiples are against the price at the moment the alert went out (`entry_price`), not the
wallet's own entry, because that is the price a reader could have had.
"""
from __future__ import annotations

from .grading import copycheck
from .ledger import Ledger
from .models import HORIZONS, Token
from .store import Store

GIVE_UP = 6 * 3600
QUIET = 3600
CALL_HORIZONS = {"x15m": 900, "x1h": 3600, "x24h": 86400}


def score_ledger(hub, ledger: Ledger) -> dict:
    now = hub.now()
    done = {(e["alert_id"], e["h"]) for e in ledger.entries("score")}
    copied = {e["alert_id"] for e in ledger.entries("copy")}
    counts = {"scores": 0, "copies": 0, "no_data": 0}

    for a in ledger.entries("alert"):
        due = [h for h, secs in HORIZONS.items() if (a["id"], h) not in done and now >= a["ts"] + secs]
        buy_ts = a["buy"]["ts"]
        copy_due = a["id"] not in copied and now >= buy_ts + copycheck.WINDOW
        if not due and not copy_due:
            continue
        tok = a["token"]
        token = Token(chain=a["chain"], address=tok["address"], symbol=tok["symbol"], pool=tok.get("pool") or "")
        candles = hub.candles(a["chain"], token, min(buy_ts, a["ts"]) - 120, min(now, a["ts"] + 86400))
        entry = a.get("entry_price")

        for h in due:
            target = a["ts"] + HORIZONS[h]
            before = [c for c in candles if c[0] <= target]
            if not before or not entry:
                if now >= target + GIVE_UP:
                    ledger.append("score", now, {"alert_id": a["id"], "h": h, "status": "no_data",
                                                 "x": None, "peak_x": None, "low_x": None})
                    counts["no_data"] += 1
                continue
            p = before[-1][4]
            peak = copycheck.peak_between(candles, a["ts"], target)
            low = copycheck.low_between(candles, a["ts"], target)
            status = "quiet" if target - before[-1][0] > QUIET else "ok"
            ledger.append("score", now, {
                "alert_id": a["id"], "h": h, "status": status, "x": round(p / entry, 4),
                "peak_x": round(max(peak or p, p) / entry, 4), "low_x": round(min(low or p, p) / entry, 4)})
            counts["scores"] += 1

        if copy_due:
            check = copycheck.copy_check(candles, buy_ts, a["buy"].get("price"), now=now)
            if check:
                ledger.append("copy", now, {"alert_id": a["id"], "status": "ok", **check})
                counts["copies"] += 1
            elif now >= buy_ts + copycheck.WINDOW + GIVE_UP:
                ledger.append("copy", now, {"alert_id": a["id"], "status": "no_data"})
                counts["no_data"] += 1
    return counts


def score_calls(hub, store: Store, limit: int = 8) -> int:
    """Age caller mentions: what the coin did 15m, 1h and 24h after each one."""
    now = hub.now()
    n = 0
    for call in store.unscored_calls(before=now - 86400, limit=limit):
        token = hub.token(call.chain, call.token) or Token(chain=call.chain, address=call.token)
        candles = hub.candles(call.chain, token, call.ts - 300, call.ts + 86400)
        base = call.price_usd or copycheck.price_at(candles, call.ts)
        if candles and base:
            for field, secs in CALL_HORIZONS.items():
                p = copycheck.price_at(candles, call.ts + secs)
                setattr(call, field, round(p / base, 4) if p else None)
        store.score_call(call)      # marked done either way, so a dead pool is not asked about forever
        n += 1
    return n
