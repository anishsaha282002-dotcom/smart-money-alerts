"""CoinGecko public API (no key): 24h market-cap change of the meme categories, as a slow second
opinion on narrative momentum."""
from __future__ import annotations

from .http import Http, num

BASE = "https://api.coingecko.com/api/v3"
# our narrative -> CoinGecko category ids (averaged)
CATEGORY = {
    "chinese": ("chinese-meme",),
    "ai": ("ai-meme-coins", "ai-agents"),
    "animals": ("dog-themed-coins", "cat-themed-coins", "frog-themed-coins"),
    "politics": ("politifi",),
    "celebrity": ("celebrity-themed-coins",),
    "binance": ("four-meme-ecosystem",),
    "stocks": ("four-meme-tokenized-stocks-4stock",),
}


def parse_categories(rows) -> dict[str, float]:
    change = {r.get("id"): num(r.get("market_cap_change_24h")) for r in rows or [] if isinstance(r, dict)}
    out = {}
    for key, ids in CATEGORY.items():
        vals = [change[i] for i in ids if change.get(i) is not None]
        if vals:
            out[key] = round(sum(vals) / len(vals), 2)
    return out


class CoinGecko:
    name = "coingecko"

    def __init__(self, http: Http | None = None):
        self.http = http or Http("coingecko", BASE, max_per_min=8)

    def categories(self) -> dict[str, float]:
        return parse_categories(self.http.get("/coins/categories"))
