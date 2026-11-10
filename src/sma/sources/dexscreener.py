"""DexScreener public API (keyless, ~300 calls/min)."""
from __future__ import annotations

from .. import http
from ..util import fnum

BASE = "https://api.dexscreener.com"


class DexScreener:
    def __init__(self):
        self.calls, self.errors = 0, []

    def _get(self, path):
        self.calls += 1
        try:
            return http.get_json(BASE + path)
        except http.HttpError as e:
            self.errors.append(f"{path.split('?')[0][:60]}: {e}")
            return None

    def tokens(self, chain, addresses):
        """Best (highest-liquidity) pair per token address."""
        best = {}
        addresses = list(dict.fromkeys(a for a in addresses if a))
        for i in range(0, len(addresses), 30):
            for p in self._get(f"/tokens/v1/{chain}/" + ",".join(addresses[i:i + 30])) or []:
                bt = p.get("baseToken") or {}
                a = bt.get("address")
                if not a:
                    continue
                key = a if chain == "solana" else a.lower()
                if fnum((p.get("liquidity") or {}).get("usd")) >= fnum((best.get(key, {}).get("liq"))):
                    best[key] = {"chain": chain, "address": a, "symbol": bt.get("symbol"), "name": bt.get("name"),
                                 "pool": p.get("pairAddress"), "dex": p.get("dexId"), "price_usd": fnum(p.get("priceUsd")),
                                 "liq": fnum((p.get("liquidity") or {}).get("usd")),
                                 "mcap": fnum(p.get("marketCap") or p.get("fdv")),
                                 "vol_h1": fnum((p.get("volume") or {}).get("h1")),
                                 "pc_h1": fnum((p.get("priceChange") or {}).get("h1")),
                                 "created_ts": int(p["pairCreatedAt"] / 1000) if p.get("pairCreatedAt") else None,
                                 "url": p.get("url")}
        return best

    def metas(self, max_metas=4):
        """DexScreener narrative 'metas' -> token rows tagged with the meta slug."""
        rows = []
        metas = self._get("/metas/trending/v1") or []
        pick = sorted(metas, key=lambda m: -fnum((m.get("marketCapChange") or {}).get("h1")))[:max_metas]
        for m in pick:
            d = self._get(f"/metas/meta/v1/{m.get('slug')}") or {}
            for p in d.get("pairs") or []:
                bt = p.get("baseToken") or {}
                if p.get("chainId") not in ("solana", "bsc", "base") or not bt.get("address"):
                    continue
                rows.append({"chain": p["chainId"], "address": bt["address"], "name": bt.get("name"), "symbol": bt.get("symbol"),
                             "vol_h1": fnum((p.get("volume") or {}).get("h1")), "pc_h1": fnum((p.get("priceChange") or {}).get("h1")),
                             "liq": fnum((p.get("liquidity") or {}).get("usd")),
                             "created_ts": int(p["pairCreatedAt"] / 1000) if p.get("pairCreatedAt") else None,
                             "sources": ["ds_meta"], "metas": [m.get("slug")]})
        return rows
