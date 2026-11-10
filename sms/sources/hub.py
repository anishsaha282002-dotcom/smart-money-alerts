"""The live hub: every data source behind one small interface, each of them optional.

The pipeline only ever talks to a hub (this one, or the demo one). A source without a key is
never constructed; a source that fails returns nothing and the others fill in what they can.

    no keys        GeckoTerminal pool trades are the only wallet-attributed data. Wallet history
                   is whatever this tool has itself seen, so grades start thin and improve.
    HELIUS         full 30-day swap history for Solana wallets on your watch list
    GMGN           smart-money and KOL feeds, wallet history and call-outs on Solana, BSC, Base
    X bearer       caller mentions and narrative post counts (needs a paid X tier)
"""
from __future__ import annotations

import logging
import time

from ..config import Settings
from ..models import Call, Token, Trade, norm
from ..store import Store
from .coingecko import CoinGecko
from .dexscreener import DexScreener
from .geckoterminal import GeckoTerminal
from .gmgn import Gmgn
from .helius import WSOL, Helius
from .jupiter import Jupiter
from .safety import Safety
from .xapi import XApi

log = logging.getLogger(__name__)
NARRATIVE_QUERIES = {"ai": "(AI agent memecoin) -is:retweet", "chinese": "(中文 meme OR 四 meme OR four.meme) -is:retweet",
                     "animals": "(dog coin OR cat coin OR frog coin) memecoin -is:retweet",
                     "politics": "(trump coin OR politifi) -is:retweet"}


class LiveHub:
    demo = False

    def __init__(self, settings: Settings, store: Store, clock=time.time):
        self.s, self.store, self._clock = settings, store, clock
        self.gt = GeckoTerminal(max_per_min=settings.gecko_max_per_min)
        self.ds = DexScreener()
        self.jup = Jupiter(base=settings.jupiter_base)
        self.cg = CoinGecko()
        self.helius = Helius(settings.helius_api_key, max_per_min=settings.helius_max_per_min) if settings.helius_api_key else None
        self.gmgn = Gmgn(settings.gmgn_api_key, max_per_min=settings.gmgn_max_per_min) if settings.gmgn_api_key else None
        self.x = XApi(settings.x_bearer_token) if settings.x_bearer_token else None
        self.safety_src = Safety() if settings.safety_checks else None
        self._meta: dict[tuple, dict] = {}
        self._tokens: dict[tuple, tuple[float, Token]] = {}
        self._cache: dict[str, tuple[float, object]] = {}

    # ------------------------------------------------------------------ misc

    def now(self) -> int:
        return int(self._clock())

    def _cached(self, key: str, ttl: int, fn):
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < ttl:
            return hit[1]
        value = fn()
        self._cache[key] = (self._clock(), value)
        return value

    def status(self) -> list[dict]:
        rows = [("geckoterminal", self.gt, True, "keyless"), ("dexscreener", self.ds, True, "keyless"),
                ("jupiter", self.jup, True, "keyless"), ("coingecko", self.cg, True, "keyless"),
                ("helius", self.helius, bool(self.helius), "HELIUS_API_KEY"),
                ("gmgn", self.gmgn, bool(self.gmgn), "GMGN_API_KEY"),
                ("x", self.x, bool(self.x), "X_BEARER_TOKEN")]
        out = []
        for name, src, on, needs in rows:
            http = getattr(src, "http", None)
            out.append({"source": name, "on": on, "needs": needs, "requests": getattr(http, "requests", 0),
                        "failures": getattr(http, "failures", 0), "last_error": getattr(http, "last_error", "")})
        if self.safety_src:
            for http in (self.safety_src.rugcheck, self.safety_src.goplus):
                out.append({"source": http.name, "on": True, "needs": "keyless", "requests": http.requests,
                            "failures": http.failures, "last_error": http.last_error})
        return out

    # ---------------------------------------------------------------- trades

    def _sol_price(self) -> float | None:
        t = self._cached("sol", 600, lambda: self.ds.token("solana", WSOL))
        return t.price_usd if t else None

    def recent_trades(self, since: int) -> list[Trade]:
        """Everything new and wallet-attributed since `since`, buys and sells."""
        out: list[Trade] = []
        for chain in self.s.chains:
            if self.gmgn:
                for feed in (self.gmgn.smart_money, self.gmgn.kol):
                    trades, metas = feed(chain)
                    out += trades
                    for wallet, meta in metas.items():
                        self._meta[(chain, wallet)] = meta
            for wallet in (norm(chain, w) for w in self.s.watch_wallets.get(chain, [])):
                if chain == "solana" and self.helius:
                    out += self.helius.swaps(wallet, since, self._sol_price(), max_pages=1)
                elif self.gmgn:
                    out += self.gmgn.wallet_activity(chain, wallet, since, max_pages=1)
            if not self.gmgn:
                out += self._pool_tape(chain)
        return [t for t in out if t.ts > since]

    def _pool_tape(self, chain: str) -> list[Trade]:
        """Keyless discovery: the trade tape of the pools that are moving right now."""
        pools = self.trending(chain)["now"][: self.s.keyless_pools_per_chain]
        if chain == "bsc":
            four = self._cached("four", 300, lambda: self.gt.dex_pools("bsc", "four-meme"))
            pools += four[: self.s.keyless_pools_per_chain]
        out: list[Trade] = []
        seen = set()
        for token in pools:
            if not token.pool or token.pool in seen:
                continue
            seen.add(token.pool)
            self._tokens[(chain, token.address)] = (self._clock(), token)
            out += self.gt.pool_trades(chain, token, min_usd=100)
        return out

    def wallet_trades(self, chain: str, wallet: str, since: int) -> list[Trade]:
        key = f"hist:{chain}:{wallet}"
        if self.store.get(key, max_age=1800, now=self.now()) is None:
            fetched: list[Trade] = []
            if self.gmgn:
                fetched += self.gmgn.wallet_activity(chain, wallet, since)
            elif chain == "solana" and self.helius:
                fetched += self.helius.swaps(wallet, since, self._sol_price())
            self.store.add_trades(fetched)
            self.store.put(key, len(fetched), self.now())
        return self.store.wallet_trades(chain, wallet, since, self.now())

    def wallet_meta(self, chain: str, wallet: str) -> dict:
        return self._meta.get((chain, wallet), {})

    # ---------------------------------------------------------------- tokens

    def token(self, chain: str, address: str) -> Token | None:
        address = norm(chain, address)
        hit = self._tokens.get((chain, address))
        if hit and self._clock() - hit[0] < 120:
            return hit[1]
        known = hit[1] if hit else None
        token = self.ds.token(chain, address)
        if token is None or not (token.pool or (known and known.pool)):
            # DexScreener does not know it, or only as a bonding curve: GeckoTerminal has the pool
            pools = self.gt.token_pools(chain, address)
            best = max(pools, key=lambda t: t.liquidity_usd or 0) if pools else None
            if token is None:
                token = best
            elif best:
                token.pool, token.dex = best.pool, best.dex
                token.launchpad = token.launchpad or best.launchpad
        if token is None:
            return known
        if known:      # keep what the trending feed knew and the lookup did not
            token.pool = token.pool or known.pool
            token.launchpad = token.launchpad or known.launchpad
            token.name = token.name or known.name
            token.symbol = token.symbol or known.symbol
            token.created_ts = token.created_ts or known.created_ts
        self._tokens[(chain, address)] = (self._clock(), token)
        return token

    def candles(self, chain: str, token: Token, start: int, end: int) -> list[list]:
        pool = token.pool or (self.token(chain, token.address) or token).pool
        return self.gt.ohlcv(chain, pool, start, end) if pool else []

    def safety(self, chain: str, address: str) -> dict | None:
        if not self.safety_src:
            return None
        found = self.safety_src.check(chain, address)
        if self.gmgn and (not found or not found["risks"]):
            found = self.gmgn.security(chain, address) or found
        return found

    # ------------------------------------------------------------ narratives

    def trending(self, chain: str) -> dict[str, list[Token]]:
        def load():
            now = self.gt.trending(chain, "1h")
            base = self.gt.trending(chain, "24h")
            if chain == "solana":
                now += self.jup.trending("1h", 50)
                base += self.jup.trending("24h", 50)
            return {"now": now, "base": base}
        return self._cached(f"trend:{chain}", 300, load)

    def narrative_posts(self) -> dict[str, tuple[int, int]]:
        if not self.x:
            return {}

        def load():
            out = {}
            for key, query in NARRATIVE_QUERIES.items():
                counts = self.x.counts(query)
                if counts:
                    out[key] = counts
            return out
        return self._cached("posts", 1800, load)

    def categories(self) -> dict[str, float]:
        return self._cached("categories", 1800, self.cg.categories)

    # --------------------------------------------------------------- callers

    def calls(self, chain: str, token: Token) -> list[Call]:
        if self.gmgn:
            self.store.add_calls(self._cached("callouts", 120, lambda: self.gmgn.callouts(self.s.chains)))
        if self.x:
            self.store.add_calls(self._cached(f"x:{chain}:{token.address}", 600,
                                              lambda: self.x.mentions(chain, token.address, token.symbol)))
        return self.store.calls_for_token(chain, token.address, self.now())

    def caller_history(self, caller: str) -> list[Call]:
        return self.store.caller_history(caller, self.now())
