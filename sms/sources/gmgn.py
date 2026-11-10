"""GMGN OpenAPI, READ-ONLY: smart-money and KOL trade feeds, a wallet's activity, call-outs,
token security. Works for Solana, BNB Chain and Base with one free key (GMGN_API_KEY).

A Python port of the read routes of GMGNAI/gmgn-skills (MIT, Copyright (c) 2025 GMGN):
same paths, same auth (`X-APIKEY` header plus `timestamp` and `client_id` in the query).

What is deliberately NOT here: /v1/trade/* (swap, multi_swap, quote, orders, strategies),
/v1/cooking/* (token creation) and every signed route (they need a private key, and this
project never holds one). Those paths are also refused by sources/http.py, so adding a call to
one of them fails loudly instead of trading.
"""
from __future__ import annotations

import time
import uuid

from ..models import Call, Trade, norm, short
from .http import Http, num

BASE = "https://openapi.gmgn.ai"
CHAIN = {"solana": "sol", "bsc": "bsc", "base": "base"}
CHAIN_BACK = {v: k for k, v in CHAIN.items()}
READ_ROUTES = (
    "/v1/user/smartmoney", "/v1/user/kol", "/v1/user/wallet_activity", "/v1/user/wallet_stats",
    "/v1/token/info", "/v1/token/security", "/v1/market/rank", "/v1/market/token_kline",
    "/v1/callout/global", "/v1/callout/get_record",
)
# listed so the test suite can assert none of them is ever requested
WRITE_ROUTES = (
    "/v1/trade/swap", "/v1/trade/multi_swap", "/v1/trade/strategy/create", "/v1/trade/strategy/cancel",
    "/v1/trade/quote", "/v1/trade/query_order", "/v1/trade/strategy/orders", "/v1/trade/follow_wallet",
    "/v1/cooking/create_token", "/v1/user/wallet_holdings",
)


def parse_track(data, chain: str) -> tuple[list[Trade], dict[str, dict]]:
    """Smart-money / KOL feed -> trades, plus what GMGN says about each wallet (tags, name, X handle)."""
    trades, metas = [], {}
    for r in (data or {}).get("list") or []:
        wallet, token, side = norm(chain, r.get("maker")), norm(chain, r.get("base_address")), r.get("side")
        ts = r.get("timestamp")
        if not wallet or not token or side not in ("buy", "sell") or not ts:
            continue
        bt = r.get("base_token") or {}
        info = r.get("maker_info") or {}
        trades.append(Trade(
            chain=chain, wallet=wallet, token=token, side=side, ts=int(ts),
            usd=num(r.get("amount_usd"), 0.0), token_amount=num(r.get("token_amount"), 0.0),
            price_usd=num(r.get("price_usd")), tx=r.get("transaction_hash") or "", symbol=bt.get("symbol") or "",
            token_created_ts=int(bt["token_create_time"]) if bt.get("token_create_time") else None, source="gmgn",
        ))
        metas[wallet] = {"tags": list(info.get("tags") or []), "name": info.get("name") or info.get("twitter_name") or "",
                         "twitter": info.get("twitter_username") or ""}
    return trades, metas


def parse_activity(data, chain: str, wallet: str) -> tuple[list[Trade], str]:
    trades = []
    for r in (data or {}).get("activities") or []:
        kind = r.get("event_type") or r.get("type")
        tok = r.get("token") or {}
        if kind not in ("buy", "sell") or not tok.get("address") or not r.get("timestamp"):
            continue
        trades.append(Trade(
            chain=chain, wallet=norm(chain, wallet), token=norm(chain, tok["address"]), side=kind, ts=int(r["timestamp"]),
            usd=num(r.get("cost_usd"), 0.0), token_amount=num(r.get("token_amount"), 0.0),
            price_usd=num(r.get("price_usd")), tx=r.get("tx_hash") or "", symbol=tok.get("symbol") or "", source="gmgn",
        ))
    return trades, (data or {}).get("next") or ""


def parse_callouts(data) -> list[Call]:
    rows = (data or {}).get("list") or (data or {}).get("call_out_records") or []
    out = []
    for r in rows:
        chain = CHAIN_BACK.get(r.get("chain") or "")
        if not chain or not r.get("call_token") or not r.get("create_time"):
            continue
        thesis = r.get("call_thesis") or {}
        out.append(Call(
            caller=r.get("twitter_username") or short(r.get("call_wallet") or "?"), chain=chain,
            token=norm(chain, r["call_token"]),
            ts=int(int(r["create_time"]) / 1000), price_usd=num(r.get("call_price")),
            text=(thesis.get("source_content") or "")[:280],
        ))
    return out


def parse_security(data) -> dict:
    d = data or {}
    risks = []
    if str(d.get("is_honeypot")).lower() in ("1", "true", "yes"):
        risks.append("flagged as a honeypot (may be unsellable)")
    for side in ("buy_tax", "sell_tax"):
        tax = num(d.get(side))
        if tax is not None and tax > 0.10:
            risks.append(f"{side.replace('_', ' ')} {tax * 100:.0f}%")
    top10 = num(d.get("top_10_holder_rate"))
    if top10 is not None and top10 > 0.5:
        risks.append(f"top 10 holders own {top10 * 100:.0f}%")
    bundlers = num(d.get("bundler_trader_amount_rate"))
    if bundlers is not None and bundlers > 0.3:
        risks.append(f"{bundlers * 100:.0f}% of volume from bundlers")
    rats = num(d.get("rat_trader_amount_rate"))
    if rats is not None and rats > 0.2:
        risks.append(f"{rats * 100:.0f}% of volume from insider wallets")
    return {"source": "gmgn", "risks": risks}


class Gmgn:
    name = "gmgn"

    def __init__(self, api_key: str, http: Http | None = None, max_per_min: int = 30):
        self.http = http or Http("gmgn", BASE, max_per_min=max_per_min)
        self.api_key = api_key

    def _call(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        if path not in READ_ROUTES:
            raise ValueError(f"gmgn: {path} is not on the read-only route list")
        q = {**(query or {}), "timestamp": int(time.time()), "client_id": str(uuid.uuid4())}
        out = self.http.request(method, path, params=q, json_body=body,
                                headers={"X-APIKEY": self.api_key, "Content-Type": "application/json"})
        if not isinstance(out, dict) or out.get("code") != 0:
            if isinstance(out, dict):
                self.http._warn("api", f"API error {out.get('code')}: {str(out.get('message') or out.get('error'))[:80]}")
            return None
        return out.get("data")

    def smart_money(self, chain: str, limit: int = 100):
        return parse_track(self._call("GET", "/v1/user/smartmoney", {"chain": CHAIN[chain], "limit": limit}), chain)

    def kol(self, chain: str, limit: int = 100):
        return parse_track(self._call("GET", "/v1/user/kol", {"chain": CHAIN[chain], "limit": limit}), chain)

    def wallet_activity(self, chain: str, wallet: str, since: int, max_pages: int = 4) -> list[Trade]:
        out, cursor = [], ""
        for _ in range(max_pages):
            q = {"chain": CHAIN[chain], "wallet_address": wallet, "limit": 50, "type": ["buy", "sell"]}
            if cursor:
                q["cursor"] = cursor
            trades, cursor = parse_activity(self._call("GET", "/v1/user/wallet_activity", q), chain, wallet)
            out += [t for t in trades if t.ts > since]
            if not cursor or not trades or min(t.ts for t in trades) <= since:
                break
        return out

    def callouts(self, chains: tuple[str, ...], only_kol: bool = False, limit: int = 50) -> list[Call]:
        body = {"chains": [CHAIN[c] for c in chains if c in CHAIN], "limit": limit}
        if only_kol:
            body["only_kol"] = True
        return parse_callouts(self._call("POST", "/v1/callout/global", body=body))

    def security(self, chain: str, token: str) -> dict | None:
        data = self._call("GET", "/v1/token/security", {"chain": CHAIN[chain], "address": token})
        return parse_security(data) if data else None
