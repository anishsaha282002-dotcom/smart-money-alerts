"""CoinGecko public API (keyless): native coin prices for SOL/BNB/ETH -> USD conversion."""
from __future__ import annotations

from .. import http

IDS = {"solana": "solana", "bsc": "binancecoin", "base": "ethereum"}
UNIT = {"solana": "sol", "bsc": "bnb", "base": "eth"}


class CoinGecko:
    def __init__(self):
        self.calls, self.errors = 0, []

    def native_prices(self):
        self.calls += 1
        try:
            d = http.get_json("https://api.coingecko.com/api/v3/simple/price",
                              params={"ids": ",".join(IDS.values()), "vs_currencies": "usd"}) or {}
        except http.HttpError as e:
            self.errors.append(str(e))
            return {}
        return {UNIT[c]: (d.get(i) or {}).get("usd") for c, i in IDS.items() if (d.get(i) or {}).get("usd")}
