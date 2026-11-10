"""Solana wallet history, read-only.

* SolanaRPC - keyless public JSON-RPC (getSignaturesForAddress + getTransaction). Slow and
  rate-limited, so it is budgeted per run and cached in sqlite.
* Helius - free-plan Parsed Streams SQLite (if stream_worker is fresh) or
  Parsed Events history at ~10 credits/request (HELIUS_API_KEY). The legacy
  100-credit Enhanced Transactions endpoint is not used.

Both reduce a transaction to the wallet's own balance changes: one memecoin up and SOL/WSOL
or a USD stable down = buy; the reverse = sell. Values are in SOL (or USD for stable legs).
Token-account rent (~0.002 SOL) is included in buy cost, which slightly understates returns.
Note: famous leaderboard wallets are often flooded with failed spam transactions, so the
keyless RPC path may find few real swaps for them; Helius (type=SWAP filter) avoids that.
"""
from __future__ import annotations

from collections import defaultdict

from .. import http
from ..util import fnum

WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
           "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB"}
DUST = 1e-9


def classify(wallet, ts, sig, sol_delta, token_deltas, source):
    """sol_delta in SOL (fee already added back), token_deltas {mint: ui amount}."""
    td = dict(token_deltas)
    sol = sol_delta + td.pop(WSOL, 0.0)
    usd = sum(td.pop(m, 0.0) for m in list(td) if m in STABLES)
    movers = {m: d for m, d in td.items() if abs(d) > DUST}
    if len(movers) != 1:
        return None                      # multi-token or no-token tx: not a simple buy/sell
    mint, d = next(iter(movers.items()))
    if d > 0 and (sol < -DUST or usd < -DUST):
        side, value, unit = "buy", (-usd if usd < -DUST else -sol), ("usd" if usd < -DUST else "sol")
    elif d < 0 and (sol > DUST or usd > DUST):
        side, value, unit = "sell", (usd if usd > DUST else sol), ("usd" if usd > DUST else "sol")
    else:
        return None
    return {"chain": "solana", "wallet": wallet, "token": mint, "side": side, "ts": int(ts or 0),
            "token_amount": abs(d), "value": value, "value_unit": unit, "price_usd": None, "tx": sig, "source": source}


def parse_rpc_tx(tx, wallet):
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return None
    meta, msg = tx["meta"], tx["transaction"]["message"]
    raw_keys = msg.get("accountKeys") or []
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in raw_keys]
    if wallet not in keys:
        return None
    i = keys.index(wallet)
    if isinstance(raw_keys[i], dict) and raw_keys[i].get("signer") is False:
        return None                      # wallet did not sign: someone else's tx touching it (spam, airdrop)
    lam = meta["postBalances"][i] - meta["preBalances"][i]
    if i == 0:
        lam += meta.get("fee") or 0
    deltas = defaultdict(float)
    for sign, arr in ((-1, meta.get("preTokenBalances") or []), (1, meta.get("postTokenBalances") or [])):
        for b in arr:
            if b.get("owner") == wallet:
                deltas[b["mint"]] += sign * fnum((b.get("uiTokenAmount") or {}).get("uiAmountString")
                                                 or (b.get("uiTokenAmount") or {}).get("uiAmount"))
    sig = (tx.get("transaction") or {}).get("signatures", [""])[0]
    return classify(wallet, tx.get("blockTime"), sig, lam / 1e9, deltas, "solana_rpc")


def parse_helius_tx(tx, wallet):
    if tx.get("transactionError"):
        return None
    lam = 0
    deltas = defaultdict(float)
    for ad in tx.get("accountData") or []:
        if ad.get("account") == wallet:
            lam += int(ad.get("nativeBalanceChange") or 0)
        for tb in ad.get("tokenBalanceChanges") or []:
            if tb.get("userAccount") == wallet:
                raw = tb.get("rawTokenAmount") or {}
                deltas[tb["mint"]] += fnum(raw.get("tokenAmount")) / (10 ** int(raw.get("decimals") or 0))
    if tx.get("feePayer") == wallet:
        lam += int(tx.get("fee") or 0)
    return classify(wallet, tx.get("timestamp"), tx.get("signature"), lam / 1e9, deltas, "helius")


class SolanaRPC:
    def __init__(self, url=None, tx_budget=60):
        self.url = url or "https://api.mainnet-beta.solana.com"
        self.budget, self.calls, self.errors = tx_budget, 0, []

    def _rpc(self, method, params):
        if self.calls >= self.budget:
            self.errors.append("budget reached")
            return None
        self.calls += 1
        try:
            r = http.post_json(self.url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except http.HttpError as e:
            self.errors.append(f"{method}: {e}")
            return None
        if (r or {}).get("error"):
            self.errors.append(f"{method}: {r['error']}")
            return None
        return (r or {}).get("result")

    def signatures(self, wallet, limit=25, before=None):
        opts = {"limit": limit}
        if before:
            opts["before"] = before
        return [s for s in (self._rpc("getSignaturesForAddress", [wallet, opts]) or []) if s.get("err") is None]

    def trades(self, wallet, since_ts, known_sigs=(), max_tx=None):
        out, n, before = [], 0, None
        max_tx = max_tx or self.budget
        known = set(known_sigs)
        while n < max_tx and self.calls < self.budget:
            sigs = self.signatures(wallet, 1000, before)   # busy/spammed wallets: most sigs are failed spam
            if not sigs:
                break
            for s in sigs:
                before = s["signature"]
                if (s.get("blockTime") or 0) < since_ts:
                    return out
                if s["signature"] in known:
                    continue
                if n >= max_tx or self.calls >= self.budget:
                    return out
                tx = self._rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                                  "maxSupportedTransactionVersion": 1}])
                n += 1
                t = parse_rpc_tx(tx, wallet)
                if t:
                    out.append(t)
        return out


class Helius:
    def __init__(self, api_key, budget=40, db_path=None):
        self.key, self.budget, self.calls, self.errors = api_key, budget, 0, []
        from .. import helius_stream as HS
        self.HS = HS
        self.store = HS.SwapStore(db_path)

    def trades(self, wallet, since_ts, pages=5):
        """Prefer the live stream store; fall back to Parsed Events (~10 credits)."""
        if self.store.worker_fresh():
            evs = self.store.events_since(since_ts, [wallet])
            return [self.HS.to_sma_trade(e) for e in evs if e.get("wallet") == wallet]
        out = []
        wallets = [{"address": wallet}]
        before = None
        for _ in range(pages):
            if self.calls >= self.budget:
                self.errors.append("budget reached")
                break
            items, cost, err = self.HS.poll_parsed_history(self.key, wallet, since_ts, limit=100)
            self.calls += 1
            if err:
                self.errors.append(err)
                break
            rows = self.HS.parse_history_items(items, wallets, since_ts, source="poll")
            self.store.insert_many(rows)
            if cost:
                self.store.bump_credits(cost)
            for ev in rows:
                out.append(self.HS.to_sma_trade(ev))
            if not items or len(items) < 100:
                break
            # page backwards if the oldest is still inside the window
            oldest = None
            for it in items:
                tx = self.HS.unwrap_tx(it)
                ts = tx.get("timestamp") or tx.get("blockTime") or 0
                try:
                    ts = int(ts or 0)
                except Exception:
                    ts = 0
                if ts and (oldest is None or ts < oldest):
                    oldest = ts
            if oldest and oldest < since_ts:
                break
        return out
