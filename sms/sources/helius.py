"""Helius, read-only. The live path is the Parsed Streams store when its heartbeat
is under two minutes old, then Parsed Events history at about 10 credits a request.
The 100-credit Enhanced Transactions history endpoint is not called.

`parse_swap` is kept for fixture tests. It is adapted from cvxv666/fomo-robinhood-radar
(MIT), fomo_agent/sources/helius.py, Copyright (c) 2026 fomo-agent contributors.
"""
from __future__ import annotations

from ..models import Trade
from .http import Http

BASE = "https://api.helius.xyz"
LAMPORTS = 1_000_000_000
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}   # USDT


def _amt(x: dict | None) -> float:
    if not x:
        return 0.0
    raw = x.get("rawTokenAmount")
    if raw:
        try:
            return float(raw.get("tokenAmount", 0)) / (10 ** int(raw.get("decimals", 0)))
        except (TypeError, ValueError):
            return 0.0
    return float(x.get("tokenAmount") or x.get("amount") or 0)


def parse_swap(tx: dict, address: str, sol_price: float | None = None) -> Trade | None:
    """One enhanced transaction -> a Trade for `address`, or None if it is not a plain buy or sell."""
    sig, ts = tx.get("signature"), tx.get("timestamp")
    if not sig or not ts:
        return None
    sol_out = sol_in = 0.0
    tok_out: dict[str, float] = {}
    tok_in: dict[str, float] = {}

    swap = (tx.get("events") or {}).get("swap")
    if swap:
        ni, no = swap.get("nativeInput"), swap.get("nativeOutput")
        if ni and ni.get("account") == address:
            sol_out += float(ni.get("amount", 0)) / LAMPORTS
        if no and no.get("account") == address:
            sol_in += float(no.get("amount", 0)) / LAMPORTS
        for ti in swap.get("tokenInputs") or []:
            if ti.get("userAccount") == address:
                tok_out[ti["mint"]] = tok_out.get(ti["mint"], 0) + _amt(ti)
        for to in swap.get("tokenOutputs") or []:
            if to.get("userAccount") == address:
                tok_in[to["mint"]] = tok_in.get(to["mint"], 0) + _amt(to)
    else:
        for tt in tx.get("tokenTransfers") or []:
            amt = float(tt.get("tokenAmount") or 0)
            if tt.get("fromUserAccount") == address:
                tok_out[tt["mint"]] = tok_out.get(tt["mint"], 0) + amt
            elif tt.get("toUserAccount") == address:
                tok_in[tt["mint"]] = tok_in.get(tt["mint"], 0) + amt
        for nt in tx.get("nativeTransfers") or []:
            amt = float(nt.get("amount", 0)) / LAMPORTS
            if nt.get("fromUserAccount") == address:
                sol_out += amt
            elif nt.get("toUserAccount") == address:
                sol_in += amt

    sol_out += tok_out.pop(WSOL, 0.0)
    sol_in += tok_in.pop(WSOL, 0.0)
    stable_out = sum(v for m, v in tok_out.items() if m in STABLES)
    stable_in = sum(v for m, v in tok_in.items() if m in STABLES)
    tok_out = {m: v for m, v in tok_out.items() if m not in STABLES}
    tok_in = {m: v for m, v in tok_in.items() if m not in STABLES}

    def usd(sol: float, stable: float) -> float:
        return stable + (sol * sol_price if sol_price else 0.0)

    if len(tok_in) == 1 and not tok_out and (sol_out > 0 or stable_out > 0):
        mint, amount = next(iter(tok_in.items()))
        value = usd(sol_out, stable_out)
        return Trade(chain="solana", wallet=address, token=mint, side="buy", ts=int(ts), usd=value,
                     token_amount=amount, price_usd=value / amount if amount and value else None, tx=sig, source="helius")
    if len(tok_out) == 1 and not tok_in and (sol_in > 0 or stable_in > 0):
        mint, amount = next(iter(tok_out.items()))
        value = usd(sol_in, stable_in)
        return Trade(chain="solana", wallet=address, token=mint, side="sell", ts=int(ts), usd=value,
                     token_amount=amount, price_usd=value / amount if amount and value else None, tx=sig, source="helius")
    return None       # token-to-token and multi-leg swaps are skipped rather than guessed at


class Helius:
    name = "helius"

    def __init__(self, api_key: str, http: Http | None = None, max_per_min: int = 60,
                 db_path: str | None = None):
        from .helius_stream import HELIUS_RPC, SwapStore
        self.api_key = api_key
        self.http = http or Http("helius", HELIUS_RPC, max_per_min=max_per_min)
        self.store = SwapStore(db_path)

    def _from_store(self, address: str, since: int) -> list[Trade]:
        from .helius_stream import to_sma_trade
        out = []
        for ev in self.store.events_since(since, [address]):
            if ev.get("wallet") != address:
                continue
            row = to_sma_trade(ev)
            out.append(Trade(chain="solana", wallet=address, token=row["token"], side=row["side"],
                             ts=row["ts"], usd=0.0, token_amount=float(row["token_amount"] or 0),
                             tx=row["tx"], source="helius_stream"))
        return out

    def _parsed_events(self, address: str, since: int, pages: int) -> list[Trade]:
        """POST /v1/parsed-events/transaction-history. About 10 credits. Not Enhanced history."""
        from .helius_stream import parse_history_items
        out: list[Trade] = []
        for _ in range(max(1, pages)):
            body = self.http.request(
                "POST", "/v1/parsed-events/transaction-history",
                params={"api-key": self.api_key},
                json_body={"address": address, "limit": 100, "sortOrder": "desc",
                           "commitment": "confirmed", "status": "succeeded",
                           "tokenAccounts": "balanceChanged",
                           **({"time": {"gte": int(since)}} if since else {})})
            if body is None:
                break
            data = body
            if isinstance(body, dict):
                data = body.get("data", body.get("result", body))
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
            if not isinstance(data, list) or not data:
                break
            rows = parse_history_items(data, [{"address": address}], since, "poll")
            self.store.insert_many(rows)
            self.store.bump_credits(10)
            for ev in rows:
                row = ev
                out.append(Trade(chain="solana", wallet=address, token=row["mint"], side=row["side"],
                                 ts=int(row.get("timestamp") or 0), usd=0.0,
                                 token_amount=float(row.get("amount") or 0),
                                 tx=row.get("signature") or "", source="helius"))
            if len(data) < 100:
                break
        return out

    def swaps(self, address: str, since: int, sol_price: float | None = None, max_pages: int = 1) -> list[Trade]:
        if self.store.worker_fresh():
            return self._from_store(address, since)
        return self._parsed_events(address, since, max_pages)
