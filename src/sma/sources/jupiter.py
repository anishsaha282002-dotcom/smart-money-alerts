"""Jupiter token API (keyless). Read-only token stats - no quote/swap endpoints are used."""
from __future__ import annotations

from .. import http
from ..util import fnum


class Jupiter:
    def __init__(self):
        self.calls, self.errors = 0, []

    def trending(self, limit=40):
        self.calls += 1
        try:
            d = http.get_json("https://lite-api.jup.ag/tokens/v2/toptrending/1h", params={"limit": limit}) or []
        except http.HttpError as e:
            self.errors.append(str(e))
            return []
        out = []
        for x in d:
            s1 = x.get("stats1h") or {}
            out.append({"chain": "solana", "address": x.get("id"), "name": x.get("name"), "symbol": x.get("symbol"),
                        "vol_h1": fnum(s1.get("buyVolume")) + fnum(s1.get("sellVolume")),
                        "pc_h1": fnum(s1.get("priceChange")), "liq": fnum(x.get("liquidity")),
                        "organic": x.get("organicScoreLabel"), "sources": ["jup_trending"], "metas": []})
        return out
