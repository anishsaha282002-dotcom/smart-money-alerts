"""GeckoTerminal public API (keyless, ~30 calls/min): pools, recent trades with wallet
addresses, and OHLCV candles. four.meme pools are the BSC dex id 'four-meme'."""
from __future__ import annotations

from .. import http
from ..util import fnum, parse_iso

BASE = "https://api.geckoterminal.com/api/v2"
NET = {"solana": "solana", "bsc": "bsc", "base": "base"}


class GeckoTerminal:
    def __init__(self, budget=25):
        self.budget, self.calls, self.errors = budget, 0, []

    def _get(self, path, params=None):
        if self.calls >= self.budget:
            self.errors.append("budget reached")
            return None
        self.calls += 1
        try:
            return http.get_json(BASE + path, params=params, headers={"Accept": "application/json;version=20230302"})
        except http.HttpError as e:
            self.errors.append(f"{path.split('?')[0]}: {e}")
            return None

    @staticmethod
    def _pool_rows(d, chain, source):
        out = []
        for p in (d or {}).get("data") or []:
            a = p.get("attributes") or {}
            base = ((p.get("relationships") or {}).get("base_token") or {}).get("data", {}).get("id", "")
            addr = base.split("_", 1)[1] if "_" in base else None
            if not addr:
                continue
            created = a.get("pool_created_at")
            out.append({"chain": chain, "address": addr, "pool": a.get("address"),
                        "name": (a.get("name") or "").split(" / ")[0], "symbol": (a.get("name") or "").split(" / ")[0],
                        "vol_h1": fnum((a.get("volume_usd") or {}).get("h1")),
                        "pc_h1": fnum((a.get("price_change_percentage") or {}).get("h1")),
                        "liq": fnum(a.get("reserve_in_usd")), "price_usd": fnum(a.get("base_token_price_usd")),
                        "mcap": fnum(a.get("market_cap_usd") or a.get("fdv_usd")),
                        "created_ts": parse_iso(created) if created else None,
                        "dex": ((p.get("relationships") or {}).get("dex") or {}).get("data", {}).get("id"),
                        "sources": [source], "metas": []})
        return out

    def trending_pools(self, chain):
        return self._pool_rows(self._get(f"/networks/{NET[chain]}/trending_pools", {"duration": "1h"}), chain, "gecko_trending")

    def new_pools(self, chain):
        return self._pool_rows(self._get(f"/networks/{NET[chain]}/new_pools"), chain, "gecko_new")

    def fourmeme_pools(self):
        return self._pool_rows(self._get("/networks/bsc/dexes/four-meme/pools", {"sort": "h24_volume_usd_desc"}),
                               "bsc", "gecko_fourmeme")

    def pool_trades(self, chain, pool, min_usd=0):
        d = self._get(f"/networks/{NET[chain]}/pools/{pool}/trades",
                      {"trade_volume_in_usd_greater_than": int(min_usd) if min_usd else None})
        out = []
        for t in (d or {}).get("data") or []:
            a = t.get("attributes") or {}
            if a.get("is_anomalous"):
                continue
            kind = a.get("kind")
            tok = a.get("to_token_address") if kind == "buy" else a.get("from_token_address")
            amt = fnum(a.get("to_token_amount") if kind == "buy" else a.get("from_token_amount"))
            px = fnum(a.get("price_to_in_usd") if kind == "buy" else a.get("price_from_in_usd"))
            out.append({"chain": chain, "wallet": a.get("tx_from_address"), "token": tok, "side": kind,
                        "ts": parse_iso(a["block_timestamp"]), "token_amount": amt,
                        "value": fnum(a.get("volume_in_usd")), "value_unit": "usd", "usd": fnum(a.get("volume_in_usd")),
                        "price_usd": px or None, "tx": a.get("tx_hash"), "source": "geckoterminal_trades", "pool": pool})
        return out

    def ohlcv(self, chain, pool, start_ts, end_ts):
        span_min = max(1, (end_ts - start_ts) / 60)
        if span_min <= 1000:
            tf, agg, limit = "minute", 1, int(span_min) + 2
        elif span_min <= 5000:
            tf, agg, limit = "minute", 5, int(span_min / 5) + 2
        else:
            tf, agg, limit = "minute", 15, min(1000, int(span_min / 15) + 2)
        d = self._get(f"/networks/{NET[chain]}/pools/{pool}/ohlcv/{tf}",
                      {"aggregate": agg, "before_timestamp": int(end_ts) + 60, "limit": min(limit, 1000),
                       "currency": "usd", "token": "base"})
        rows = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        return sorted((int(r[0]), fnum(r[1]), fnum(r[2]), fnum(r[3]), fnum(r[4]), fnum(r[5])) for r in rows)
