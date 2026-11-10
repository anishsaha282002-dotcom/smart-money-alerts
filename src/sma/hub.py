"""Data hubs: one interface, two implementations.

LiveHub stitches the free sources together (each optional); DemoHub replays bundled
fixtures so the whole pipeline runs with zero keys and zero network.
"""
from __future__ import annotations

import json
from pathlib import Path

from .sources.coingecko import CoinGecko
from .sources.dexscreener import DexScreener
from .sources.geckoterminal import GeckoTerminal
from .sources.gmgn import GMGN
from .sources.jupiter import Jupiter
from .sources.solana import Helius, SolanaRPC
from .sources.xapi import XRecentSearch
from .util import norm_addr


class LiveHub:
    demo = False

    def __init__(self, cfg, store):
        env, b, d = cfg["env"], cfg["budgets"], cfg["discovery"]
        self.cfg, self.store = cfg, store
        self.gt = GeckoTerminal(b["geckoterminal"])
        self.ds = DexScreener()
        self.jup = Jupiter()
        self.cg = CoinGecko()
        self.rpc = SolanaRPC(env.get("SOLANA_RPC_URL") or None, d["solana_rpc_tx_budget"])
        db = (cfg["paths"].get("helius_stream_db") or env.get("HELIUS_STREAM_DB") or "").strip() or None
        self.helius = Helius(env["HELIUS_API_KEY"], b["helius"], db_path=db) if env.get("HELIUS_API_KEY") else None
        self.gmgn = GMGN(env["GMGN_API_KEY"], b["gmgn"]) if env.get("GMGN_API_KEY") else None
        self.x = XRecentSearch(env["X_BEARER_TOKEN"], b["x"]) if env.get("X_BEARER_TOKEN") else None
        self._tok, self._ohlcv, self._pools = {}, {}, {}
        self._native = None
        wpath = Path(cfg["root"]) / cfg["paths"]["wallets"]
        self.tracked = json.loads(wpath.read_text())["wallets"] if wpath.exists() else []

    # ---------- status ----------
    def status(self):
        def st(obj, name, missing=None):
            if obj is None:
                return {"source": name, "state": f"off ({missing})"}
            return {"source": name, "state": "error" if obj.errors and not obj.calls else "ok",
                    "calls": obj.calls, "errors": obj.errors[:3]}
        return [st(self.gt, "GeckoTerminal (keyless)"), st(self.ds, "DexScreener (keyless)"),
                st(self.jup, "Jupiter (keyless)"), st(self.cg, "CoinGecko (keyless)"),
                st(self.rpc, "Solana public RPC (keyless)"),
                st(self.helius, "Helius", "no HELIUS_API_KEY"), st(self.gmgn, "GMGN read-only", "no GMGN_API_KEY"),
                st(self.x, "X API", "no X_BEARER_TOKEN")]

    def native_prices(self):
        if self._native is None:
            self._native = self.cg.native_prices()
        return self._native

    # ---------- discovery ----------
    def _discovery_pools(self):
        if not self._pools:
            d = self.cfg["discovery"]
            rows = []
            for ch in self.cfg["chains"]:
                rows += self.gt.trending_pools(ch)[: max(d["gecko_trending_pools"] * 3, 10)]
            if "bsc" in self.cfg["chains"]:
                rows += self.gt.fourmeme_pools()
            self._pools = rows
        return self._pools

    def recent_buys(self, since_ts, now_ts):
        buys = []
        d = self.cfg["discovery"]
        if self.gmgn:
            for ch in self.cfg["chains"]:
                for kind in ("smartmoney", "kol"):
                    buys += self.gmgn.smart_buys(ch, since_ts, kind)
        for w in self.tracked:
            ch = w.get("chain", "solana")
            if ch not in self.cfg["chains"]:
                continue
            got = []
            if ch == "solana" and self.helius:
                got = self.helius.trades(w["address"], since_ts, pages=1)
            elif ch == "solana":
                got = self.rpc.trades(w["address"], since_ts, self.store.known_txs(ch, w["address"]), max_tx=6)
            elif self.gmgn:
                got = self.gmgn.wallet_trades(ch, w["address"], since_ts, pages=1)
            self.store.add_trades(got)
            for t in got:
                if t["side"] == "buy":
                    buys.append({**t, "label": w.get("name", ""), "tracked": True})
        pools = self._discovery_pools()
        per_chain = {}
        for p in sorted(pools, key=lambda p: -(p.get("vol_h1") or 0)):
            lim = d["fourmeme_pools"] if "gecko_fourmeme" in p["sources"] else d["gecko_trending_pools"]
            k = (p["chain"], "fm" if "gecko_fourmeme" in p["sources"] else "tr")
            if per_chain.get(k, 0) >= lim:
                continue
            per_chain[k] = per_chain.get(k, 0) + 1
            trades = self.gt.pool_trades(p["chain"], p["pool"], min_usd=50)
            for t in trades:
                t["token"] = norm_addr(t["chain"], t["token"])
                t["wallet"] = norm_addr(t["chain"], t["wallet"])
                t["symbol"] = p.get("symbol", "")
            self.store.add_trades(trades)          # observed history: grows every run, keyless
            buys += [t for t in trades if t["side"] == "buy" and t["ts"] >= since_ts]
        return buys

    def wallet_trades(self, chain, wallet, since_ts, now_ts, allow_fetch=True):
        src, fetched = self.store.fetched(chain, wallet)
        if allow_fetch and now_ts - fetched > 1800:
            got, src = [], "observed"
            if self.gmgn:
                got, src = self.gmgn.wallet_trades(chain, wallet, since_ts), "gmgn_activity"
            elif chain == "solana" and self.helius:
                got, src = self.helius.trades(wallet, since_ts), "helius"
            elif chain == "solana" and self.rpc.calls < self.rpc.budget:
                got, src = self.rpc.trades(wallet, since_ts, self.store.known_txs(chain, wallet),
                                           max_tx=max(10, self.rpc.budget - self.rpc.calls)), "solana_rpc"
            self.store.add_trades(got)
            self.store.mark_fetched(chain, wallet, src, now_ts)
        return self.store.trades(chain, wallet, since_ts), src or "observed"

    def token_info(self, chain, token):
        key = (chain, norm_addr(chain, token))
        if key not in self._tok:
            self._tok.update({(chain, k): v for k, v in self.ds.tokens(chain, [token]).items()})
            self._tok.setdefault(key, None)
        return self._tok[key]

    def prefetch_tokens(self, chain, tokens):
        need = [t for t in tokens if (chain, norm_addr(chain, t)) not in self._tok]
        if need:
            got = self.ds.tokens(chain, need)
            self._tok.update({(chain, k): v for k, v in got.items()})
            for t in need:
                self._tok.setdefault((chain, norm_addr(chain, t)), None)

    def ohlcv(self, chain, pool, start_ts, end_ts):
        key = (chain, pool, int(start_ts) // 300, int(end_ts) // 300)
        if key not in self._ohlcv:
            self._ohlcv[key] = self.gt.ohlcv(chain, pool, start_ts, end_ts) if pool else []
        return self._ohlcv[key]

    def narrative_tokens(self):
        rows = list(self._discovery_pools())
        for ch in self.cfg["chains"]:
            if ch == "solana":
                rows += self.gt.new_pools(ch)
        rows += self.ds.metas(3)
        if "solana" in self.cfg["chains"]:
            rows += self.jup.trending()
        return [r for r in rows if r.get("chain") in self.cfg["chains"]]

    def x_posts(self, chain, info):
        if not self.x:
            return None
        return self.x.posts_about(info.get("symbol"), info.get("address"))


class DemoHub:
    """Replays fixtures/demo/*.json. No network, no keys."""
    demo = True

    def __init__(self, cfg, store, fixtures_dir):
        self.cfg, self.store = cfg, store
        self.dir = Path(fixtures_dir)
        j = lambda n: json.loads((self.dir / n).read_text(encoding="utf-8"))
        self.meta = j("meta.json")
        self._buys = j("buys.json")
        self._wallets = j("wallet_trades.json")
        self._tokens = j("tokens.json")
        self._ohlcv = j("ohlcv.json")
        self._narr = j("narrative_tokens.json")
        self._xposts = j("x_posts.json")
        self.tracked = []
        hist = j("narrative_history.json") if (self.dir / "narrative_history.json").exists() else []
        for h in hist:      # pretend earlier runs happened so NEW/RISING/FADING labels are visible
            store.save_narratives(h["ts"], [{"narrative": h["narrative"], "score": h["score"], "vol_h1": h["vol_h1"]}])

    def status(self):
        return [{"source": "demo fixtures", "state": f"ok ({self.dir})"}]

    def native_prices(self):
        return self.meta.get("native_usd", {"sol": 150.0, "bnb": 600.0, "eth": 3000.0})

    def recent_buys(self, since_ts, now_ts):
        return [b for b in self._buys if since_ts <= b["ts"] <= now_ts]

    def wallet_trades(self, chain, wallet, since_ts, now_ts, allow_fetch=True):
        rows = [t for t in self._wallets.get(f"{chain}:{wallet}", []) if since_ts <= t["ts"] <= now_ts]
        return rows, self.meta.get("wallet_source", {}).get(f"{chain}:{wallet}", "demo")

    def token_info(self, chain, token):
        return self._tokens.get(f"{chain}:{token}")

    def prefetch_tokens(self, chain, tokens):
        pass

    def ohlcv(self, chain, pool, start_ts, end_ts):
        return [tuple(c) for c in self._ohlcv.get(pool, []) if start_ts - 60 <= c[0] <= end_ts]

    def narrative_tokens(self):
        return self._narr

    def x_posts(self, chain, info):
        return self._xposts.get(f"{chain}:{info['address']}", [])
