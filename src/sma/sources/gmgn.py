"""GMGN Agent OpenAPI - READ-ONLY subset (GMGN_API_KEY, "exist auth").

Endpoint names follow the official MIT client GMGNAI/gmgn-skills (src/client/OpenApiClient.ts).
Only the paths in READ_PATHS can be called; anything else (swap, order, cooking, signed
wallet endpoints) raises before a request is built. GMGN_PRIVATE_KEY is never read.
"""
from __future__ import annotations

import time
import uuid

from .. import http
from ..safety import TradingRefused
from ..util import fnum, norm_addr

HOST = "https://openapi.gmgn.ai"
CHAIN = {"solana": "sol", "bsc": "bsc", "base": "base"}
READ_PATHS = frozenset({"/v1/user/smartmoney", "/v1/user/kol", "/v1/market/token_signal",
                        "/v1/user/wallet_activity", "/v1/token/info", "/v1/market/rank"})


class GMGN:
    def __init__(self, api_key, budget=20):
        self.key, self.budget, self.calls, self.errors = api_key, budget, 0, []

    def _call(self, method, path, query=None, body=None):
        if path not in READ_PATHS:
            raise TradingRefused(f"GMGN path not in read-only whitelist: {path}")
        if self.calls >= self.budget:
            self.errors.append("budget reached")
            return None
        self.calls += 1
        q = dict(query or {})
        q.update(timestamp=int(time.time()), client_id=str(uuid.uuid4()))
        try:
            d = http.request_json(HOST + path, method=method, params=q, body=body, headers={"X-APIKEY": self.key})
        except http.HttpError as e:
            self.errors.append(f"{path}: {e}")
            return None
        if isinstance(d, dict) and d.get("code") not in (0, "0", None):
            self.errors.append(f"{path}: code={d.get('code')} {d.get('message') or d.get('error') or ''}")
            return None
        return d.get("data", d) if isinstance(d, dict) else d

    @staticmethod
    def _list(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for k in ("list", "activities", "rank", "items", "tokens"):
                if isinstance(payload.get(k), list):
                    return payload[k]
        return []

    def smart_buys(self, chain, since_ts, kind="smartmoney"):
        d = self._call("GET", f"/v1/user/{kind}", {"chain": CHAIN[chain], "limit": 100})
        out = []
        for it in self._list(d):
            if (it.get("side") or "").lower() != "buy":
                continue
            ts = int(fnum(it.get("timestamp")))
            if ts < since_ts:
                continue
            info = it.get("maker_info") or {}
            out.append({"chain": chain, "wallet": norm_addr(chain, it.get("maker") or info.get("address") or ""),
                        "token": norm_addr(chain, it.get("base_address") or ""), "side": "buy", "ts": ts,
                        "usd": fnum(it.get("amount_usd")), "value": fnum(it.get("amount_usd")), "value_unit": "usd",
                        "price_usd": fnum(it.get("price_usd")) or None, "tx": it.get("transaction_hash") or "",
                        "symbol": (it.get("base_token") or {}).get("symbol") or "",
                        "label": info.get("twitter_username") or info.get("name") or "",
                        "tags": list(info.get("tags") or []), "source": f"gmgn_{kind}"})
        return out

    def wallet_trades(self, chain, wallet, since_ts, pages=3):
        out, cursor = [], None
        for _ in range(pages):
            d = self._call("GET", "/v1/user/wallet_activity",
                           {"chain": CHAIN[chain], "wallet_address": wallet, "limit": 50, "cursor": cursor})
            rows = self._list(d)
            for a in rows:
                et = (a.get("event_type") or "").lower()
                if et not in ("buy", "sell"):
                    continue
                ts = int(fnum(a.get("timestamp")))
                if ts < since_ts:
                    return out
                tok = (a.get("token") or {}).get("address") or a.get("token_address") or ""
                out.append({"chain": chain, "wallet": wallet, "token": norm_addr(chain, tok), "side": et, "ts": ts,
                            "token_amount": fnum(a.get("token_amount")), "value": fnum(a.get("cost_usd") or a.get("quote_amount")),
                            "value_unit": "usd", "price_usd": fnum(a.get("price_usd")) or None, "tx": a.get("tx_hash") or "",
                            "symbol": (a.get("token") or {}).get("symbol") or "", "source": "gmgn_activity"})
            cursor = d.get("next") if isinstance(d, dict) else None
            if not cursor or not rows:
                break
        return out
