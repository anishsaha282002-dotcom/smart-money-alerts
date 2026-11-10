"""Jupiter token API (no key): what is trending on Solana, with Jupiter's organic score, which
discounts wash and bot volume. The base URL is a setting because Jupiter has moved it before."""
from __future__ import annotations

from ..models import Token
from .http import Http, num


def parse_tokens(rows) -> list[Token]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        s1 = r.get("stats1h") or {}
        out.append(Token(
            chain="solana", address=r["id"], symbol=r.get("symbol") or "", name=r.get("name") or "",
            price_usd=num(r.get("usdPrice")), mcap_usd=num(r.get("mcap")) or num(r.get("fdv")),
            liquidity_usd=num(r.get("liquidity")), organic_score=num(r.get("organicScore")),
            launchpad=r.get("launchpad") or "", change_h1=num(s1.get("priceChange")),
            volume_h1=(num(s1.get("buyVolume"), 0.0) + num(s1.get("sellVolume"), 0.0)) or None,
        ))
    return out


class Jupiter:
    name = "jupiter"

    def __init__(self, http: Http | None = None, base: str = "https://lite-api.jup.ag"):
        self.http = http or Http("jupiter", base, max_per_min=30)

    def trending(self, interval: str = "1h", limit: int = 50) -> list[Token]:
        return parse_tokens(self.http.get(f"/tokens/v2/toptrending/{interval}", {"limit": limit}))
