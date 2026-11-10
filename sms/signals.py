"""Observations of wallet and caller activity. Never a trade instruction.

SM_BUYING / SM_SELLING name what was seen (wallets buying or selling), not what
the reader should do. A call or a leaderboard rank alone is not SM_BUYING.
"""
from __future__ import annotations

from .models import Trade

SM_BUYING = "sm_buying"
SM_SELLING = "sm_selling"
SM_WINDOW_S = 3600
WASH_ORGANIC = 40.0          # Jupiter organic score below this looks like wash volume


def _tracked(book: dict, chain: str, wallet: str) -> dict | None:
    row = book.get((chain, wallet))
    if row and row.get("stream"):
        return row
    return None


def cluster_wallets(trades: list[Trade], chain: str, token: str, now: int, book: dict,
                    window_s: int = SM_WINDOW_S) -> list[dict]:
    seen: dict[str, Trade] = {}
    for t in trades:
        if t.chain != chain or t.token != token or t.side != "buy":
            continue
        if t.ts < now - window_s:
            continue
        row = _tracked(book, chain, t.wallet)
        if not row:
            continue
        seen.setdefault(t.wallet, t)
    if len(seen) < 2:
        return []
    return [{"wallet": w, "name": book[(chain, w)].get("name") or "", "usd": round(t.usd, 2), "ts": t.ts}
            for w, t in sorted(seen.items(), key=lambda kv: kv[1].ts)]


def is_kol(row: dict | None) -> bool:
    if not row:
        return False
    tags = {str(t).lower() for t in row.get("tags") or []}
    return "kol" in tags


def kol_buy(chain: str, wallet: str, book: dict) -> dict | None:
    row = _tracked(book, chain, wallet)
    if is_kol(row):
        return row
    return None


def shill_block(mentions: list, organic_score: float | None, flags: list[str]) -> str | None:
    """A risk note that keeps a wallet's activity from being posted as noteworthy.

    Copy-paste shilling: three or more callers posting the same long text.
    Wash: a low Jupiter organic score, or a wallet already flagged wash or bot.
    """
    bad = {"wash", "bot"} & set(flags or [])
    if bad:
        return "Shill/wash risk flagged: wallet flagged " + ", ".join(sorted(bad))
    if organic_score is not None and organic_score < WASH_ORGANIC:
        return f"Shill/wash risk flagged: organic score {organic_score:.0f}"
    texts: dict[str, set[str]] = {}
    for m in mentions or []:
        text = " ".join((getattr(m, "text", None) or "").lower().split())
        if len(text) < 80:
            continue
        texts.setdefault(text, set()).add(getattr(m, "caller", "") or "")
    for text, authors in texts.items():
        if len(authors) >= 3:
            return f"Shill/wash risk flagged: {len(authors)} accounts posted the same text"
    return None


def soft_sell(trade: Trade, book: dict) -> dict | None:
    """Tracked smart-money or KOL selling. Reserve wallets are not included."""
    row = _tracked(book, trade.chain, trade.wallet)
    if not row or trade.side != "sell":
        return None
    kind = "kol" if is_kol(row) else "smart-money"
    name = row.get("name") or trade.wallet
    who = f"{name} (KOL)" if kind == "kol" else name
    return {"kind": kind, "name": row.get("name") or "", "wallet": trade.wallet,
            "activity": SM_SELLING, "text": f"Smart-money selling: {who} sold"}
