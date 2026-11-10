"""Keyless public Solana JSON-RPC. Used only when HELIUS_API_KEY is unset.

Reads getSignaturesForAddress and getTransaction. Never sends a transaction.
Busy wallets are mostly failed spam, so the call budget is small on purpose.
"""
from __future__ import annotations

from collections import defaultdict

from ..models import Trade
from .http import Http, num

WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
           "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}
DUST = 1e-9
DEFAULT_URL = "https://api.mainnet-beta.solana.com"


def classify(wallet: str, ts: int, sig: str, sol_delta: float, token_deltas: dict, source: str) -> Trade | None:
    td = dict(token_deltas)
    sol = sol_delta + td.pop(WSOL, 0.0)
    usd = sum(td.pop(m, 0.0) for m in list(td) if m in STABLES)
    movers = {m: d for m, d in td.items() if abs(d) > DUST}
    if len(movers) != 1:
        return None
    mint, delta = next(iter(movers.items()))
    if delta > 0 and (sol < -DUST or usd < -DUST):
        side, value = "buy", (-usd if usd < -DUST else -sol)
    elif delta < 0 and (sol > DUST or usd > DUST):
        side, value = "sell", (usd if usd > DUST else sol)
    else:
        return None
    # Stable legs are already dollars. SOL legs stay in SOL until a price is known;
    # callers that need dollars pass sol_price via `value` only when it was a stable.
    usd_value = value if (usd < -DUST or usd > DUST) else 0.0
    return Trade(chain="solana", wallet=wallet, token=mint, side=side, ts=int(ts or 0),
                 usd=usd_value, token_amount=abs(delta), tx=sig, source=source)


def parse_rpc_tx(tx: dict | None, wallet: str) -> Trade | None:
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return None
    meta, msg = tx["meta"], tx["transaction"]["message"]
    raw_keys = msg.get("accountKeys") or []
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in raw_keys]
    if wallet not in keys:
        return None
    i = keys.index(wallet)
    if isinstance(raw_keys[i], dict) and raw_keys[i].get("signer") is False:
        return None
    lam = meta["postBalances"][i] - meta["preBalances"][i]
    if i == 0:
        lam += meta.get("fee") or 0
    deltas: dict[str, float] = defaultdict(float)
    for sign, arr in ((-1, meta.get("preTokenBalances") or []), (1, meta.get("postTokenBalances") or [])):
        for b in arr:
            if b.get("owner") == wallet:
                ui = b.get("uiTokenAmount") or {}
                deltas[b["mint"]] += sign * num(ui.get("uiAmountString") or ui.get("uiAmount"), 0.0)
    sig = (tx.get("transaction") or {}).get("signatures", [""])[0]
    return classify(wallet, tx.get("blockTime") or 0, sig, lam / 1e9, deltas, "solana_rpc")


class SolanaRPC:
    name = "solana_rpc"

    def __init__(self, url: str | None = None, tx_budget: int = 60, http: Http | None = None):
        self.url = url or DEFAULT_URL
        self.budget, self.calls = tx_budget, 0
        self.http = http or Http("solana-rpc", self.url, max_per_min=30)

    def _rpc(self, method: str, params: list):
        if self.calls >= self.budget:
            return None
        self.calls += 1
        body = self.http.request("POST", self.url, json_body={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(body, dict) or body.get("error"):
            return None
        return body.get("result")

    def signatures(self, wallet: str, limit: int = 25, before: str | None = None) -> list[dict]:
        opts: dict = {"limit": limit}
        if before:
            opts["before"] = before
        rows = self._rpc("getSignaturesForAddress", [wallet, opts]) or []
        return [s for s in rows if isinstance(s, dict) and s.get("err") is None]

    def trades(self, wallet: str, since_ts: int, max_tx: int | None = None) -> list[Trade]:
        out, n, before = [], 0, None
        max_tx = max_tx if max_tx is not None else self.budget
        while n < max_tx and self.calls < self.budget:
            sigs = self.signatures(wallet, 25, before)
            if not sigs:
                break
            for s in sigs:
                before = s.get("signature")
                if (s.get("blockTime") or 0) < since_ts:
                    return out
                if n >= max_tx or self.calls >= self.budget:
                    return out
                tx = self._rpc("getTransaction", [s["signature"], {
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
                n += 1
                trade = parse_rpc_tx(tx, wallet)
                if trade and trade.ts >= since_ts:
                    out.append(trade)
        return out
