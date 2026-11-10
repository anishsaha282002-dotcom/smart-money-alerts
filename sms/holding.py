"""Is the wallet still in? The question traders ask right after "who bought".

From the wallet's own trades in one coin, how much of what it bought is still held at a moment in
time. Research behind it: the useful smart-money signal is how much of the position proven wallets
still hold, not the bare fact that they bought (a coin labelled "smart money buying" can already be
86% sold by the same wallets).
"""
from __future__ import annotations

from .models import Trade


def held_share(trades: list[Trade], token: str, at: int) -> dict | None:
    """Share of tokens bought (up to `at`) that has not been sold by `at`. None if no buy is known."""
    bought = sold = 0.0
    last_sell = None
    for t in trades:
        if t.token != token or t.ts > at:
            continue
        if t.side == "buy":
            bought += t.token_amount or 0.0
        elif t.side == "sell":
            sold += t.token_amount or 0.0
            last_sell = t.ts
    if bought <= 0:
        return None
    share = max(0.0, min(1.0, 1 - sold / bought))
    return {"held": round(share, 3), "last_sell_ts": last_sell}


def holding_text(h: dict | None, when: str = "now") -> str:
    if not h:
        return "Position size unknown (no buy amount on record)."
    held = h["held"]
    if held >= 0.98:
        return f"Still holding all of it ({when})."
    if held <= 0.02:
        return f"⚠ Already sold everything ({when})."
    return f"⚠ Already sold {round((1 - held) * 100)}%, still holds {round(held * 100)}% ({when})."
