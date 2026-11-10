"""DexScreener public API (no key): a token's best pool, price, market cap and age; boosted tokens."""
from __future__ import annotations

from ..models import Token, norm
from .http import Http, num
from .quote_tokens import pick_base_pair

BASE = "https://api.dexscreener.com"
LAUNCHPAD_DEX = {"fourmeme": "four.meme", "four-meme": "four.meme", "pumpswap": "pump.fun", "pumpfun": "pump.fun"}


def parse_pairs(pairs, chain: str, address: str | None = None) -> Token | None:
    """The deepest pool for the token is the one a buyer would actually trade in.

    When `address` is given, only pools where it is the *base* token count. Otherwise a quote
    token's deepest pool (e.g. memecoin/TTWO) would return the other coin's address and name.
    """
    pairs = [p for p in pairs or [] if isinstance(p, dict) and p.get("chainId") == chain]
    if address:
        pairs = pick_base_pair(pairs, address)
    if not pairs:
        return None
    p = max(pairs, key=lambda x: num((x.get("liquidity") or {}).get("usd"), 0.0))
    base = p.get("baseToken") or {}
    created = p.get("pairCreatedAt")
    oldest = min((x.get("pairCreatedAt") for x in pairs if x.get("pairCreatedAt")), default=created)
    return Token(
        chain=chain, address=norm(chain, base.get("address")), symbol=base.get("symbol") or "", name=base.get("name") or "",
        # bonding-curve "pairs" come back as "<token>:4meme"; that is not a pool anyone can chart
        pool="" if ":" in (p.get("pairAddress") or "") else norm(chain, p.get("pairAddress")), dex=p.get("dexId") or "", launchpad=LAUNCHPAD_DEX.get(p.get("dexId") or "", ""),
        price_usd=num(p.get("priceUsd")), mcap_usd=num(p.get("marketCap")) or num(p.get("fdv")),
        liquidity_usd=num((p.get("liquidity") or {}).get("usd")),
        created_ts=int(oldest / 1000) if oldest else None,
        change_h1=num((p.get("priceChange") or {}).get("h1")), volume_h1=num((p.get("volume") or {}).get("h1")),
    )


class DexScreener:
    name = "dexscreener"

    def __init__(self, http: Http | None = None):
        self.http = http or Http("dexscreener", BASE, max_per_min=120)

    def token(self, chain: str, address: str) -> Token | None:
        return parse_pairs(self.http.get(f"/tokens/v1/{chain}/{address}"), chain, address)

    def boosted(self, chains: tuple[str, ...]) -> list[Token]:
        """Tokens whose teams are paying for attention right now. A trending input, not an endorsement."""
        out = []
        for row in self.http.get("/token-boosts/top/v1") or []:
            if isinstance(row, dict) and row.get("chainId") in chains and row.get("tokenAddress"):
                out.append(Token(chain=row["chainId"], address=norm(row["chainId"], row["tokenAddress"]),
                                 description=row.get("description") or ""))
        return out
