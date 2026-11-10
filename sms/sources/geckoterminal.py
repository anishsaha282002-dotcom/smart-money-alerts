"""GeckoTerminal public API (no key). Trending pools, new pools, four.meme pools, a pool's trade
tape and minute candles — enough for the whole tool to run with zero keys.

Request and back-off shape adapted from cvxv666/fomo-robinhood-radar (MIT),
fomo_agent/sources/geckoterminal.py, Copyright (c) 2026 fomo-agent contributors.

  GET /networks/{net}/trending_pools?duration=5m|1h|6h|24h
  GET /networks/{net}/new_pools
  GET /networks/{net}/dexes/{dex}/pools                 (dex "four-meme" on bsc)
  GET /networks/{net}/pools/{pool}/trades               last 300 trades, with the trader's address
  GET /networks/{net}/pools/{pool}/ohlcv/minute         up to 1000 candles per call
  GET /networks/{net}/tokens/{address}/pools
"""
from __future__ import annotations

from datetime import datetime

from ..models import Token, Trade, norm
from .http import Http, num

BASE = "https://api.geckoterminal.com/api/v2"
NETWORK = {"solana": "solana", "bsc": "bsc", "base": "base"}
LAUNCHPAD_DEX = {"four-meme": "four.meme", "pumpswap": "pump.fun", "pump-fun": "pump.fun", "flap": "flap"}


def _ts(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def parse_pools(body: dict | None, chain: str) -> list[Token]:
    """Pools -> the base token of each, carrying the pool's price, liquidity and age."""
    if not body:
        return []
    tokens = {i["id"]: i.get("attributes") or {} for i in body.get("included") or [] if i.get("type") == "token"}
    out = []
    data = body.get("data") or []
    for p in data if isinstance(data, list) else [data]:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        base_id = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
        dex = ((rel.get("dex") or {}).get("data") or {}).get("id", "")
        meta = tokens.get(base_id, {})
        address = norm(chain, meta.get("address") or base_id.split("_", 1)[-1])
        if not address:
            continue
        pair_name = (a.get("name") or "").split(" / ")[0]
        out.append(Token(
            chain=chain, address=address, symbol=meta.get("symbol") or pair_name, name=meta.get("name") or pair_name,
            pool=norm(chain, a.get("address")), dex=dex, launchpad=LAUNCHPAD_DEX.get(dex, ""),
            price_usd=num(a.get("base_token_price_usd")),
            mcap_usd=num(a.get("market_cap_usd")) or num(a.get("fdv_usd")),
            liquidity_usd=num(a.get("reserve_in_usd")), created_ts=_ts(a.get("pool_created_at")),
            change_h1=num((a.get("price_change_percentage") or {}).get("h1")),
            volume_h1=num((a.get("volume_usd") or {}).get("h1")),
        ))
    return out


def parse_trades(body: dict | None, chain: str, token: Token | None = None) -> list[Trade]:
    if not body:
        return []
    out = []
    for t in body.get("data") or []:
        a = t.get("attributes") or {}
        ts, wallet, kind = _ts(a.get("block_timestamp")), a.get("tx_from_address"), a.get("kind")
        if not ts or not wallet or kind not in ("buy", "sell") or a.get("is_anomalous"):
            continue
        buy = kind == "buy"
        out.append(Trade(
            chain=chain, wallet=norm(chain, wallet), side=kind, ts=ts,
            token=norm(chain, a.get("to_token_address" if buy else "from_token_address")),
            usd=num(a.get("volume_in_usd"), 0.0),
            token_amount=num(a.get("to_token_amount" if buy else "from_token_amount"), 0.0),
            price_usd=num(a.get("price_to_in_usd" if buy else "price_from_in_usd")),
            tx=a.get("tx_hash") or "", symbol=token.symbol if token else "",
            token_created_ts=token.created_ts if token else None, source="geckoterminal",
        ))
    return out


def parse_ohlcv(body: dict | None) -> list[list]:
    """[[ts, open, high, low, close, volume], …] oldest first, one row per timestamp."""
    rows = (((body or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    by_ts = {}
    for r in rows:
        if len(r) >= 6 and r[0] not in by_ts:
            by_ts[int(r[0])] = [int(r[0]), *[float(x) for x in r[1:6]]]
    return [by_ts[k] for k in sorted(by_ts)]


class GeckoTerminal:
    name = "geckoterminal"

    def __init__(self, http: Http | None = None, max_per_min: int = 24):
        self.http = http or Http("geckoterminal", BASE, max_per_min=max_per_min)

    def trending(self, chain: str, duration: str = "1h") -> list[Token]:
        return parse_pools(self.http.get(f"/networks/{NETWORK[chain]}/trending_pools",
                                         {"duration": duration, "include": "base_token,dex"}), chain)

    def new_pools(self, chain: str) -> list[Token]:
        return parse_pools(self.http.get(f"/networks/{NETWORK[chain]}/new_pools", {"include": "base_token,dex"}), chain)

    def dex_pools(self, chain: str, dex: str) -> list[Token]:
        return parse_pools(self.http.get(f"/networks/{NETWORK[chain]}/dexes/{dex}/pools",
                                         {"include": "base_token,dex"}), chain)

    def token_pools(self, chain: str, address: str) -> list[Token]:
        return parse_pools(self.http.get(f"/networks/{NETWORK[chain]}/tokens/{address}/pools",
                                         {"include": "base_token,dex"}), chain)

    def pool_trades(self, chain: str, token: Token, min_usd: float = 0) -> list[Trade]:
        params = {"trade_volume_in_usd_greater_than": int(min_usd)} if min_usd else None
        trades = parse_trades(self.http.get(f"/networks/{NETWORK[chain]}/pools/{token.pool}/trades", params), chain, token)
        return [t for t in trades if t.token == token.address]

    def ohlcv(self, chain: str, pool: str, start: int, end: int) -> list[list]:
        """Minute candles covering start..end. Above ~16 hours it switches to 5-minute candles
        so one request still covers the span."""
        span = max(60, end - start)
        aggregate = 1 if span <= 950 * 60 else 5 if span <= 950 * 300 else 15
        body = self.http.get(f"/networks/{NETWORK[chain]}/pools/{pool}/ohlcv/minute",
                             {"aggregate": aggregate, "before_timestamp": end + 60, "limit": 1000, "currency": "usd"})
        return [c for c in parse_ohlcv(body) if start - aggregate * 60 <= c[0] <= end]
