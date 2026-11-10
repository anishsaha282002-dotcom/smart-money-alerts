"""Demo mode: a small synthetic world so the whole tool runs with zero keys and no network.

Everything is generated from sms/demo_data/scenario.json with a fixed seed: wallets with a
30-day history, coins with minute-by-minute price paths, callers with a track record, trending
lists. It is the same pipeline, scorer, ledger and site as live mode, fed by `DemoHub` instead
of `LiveHub`, with a clock the simulation moves forward by hand.

SYNTHETIC. The numbers it produces demonstrate the product, not the market. Good wallets were
*given* better odds here; nothing about real performance can be read off a demo record.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from .models import Call, Token, Trade

SCENARIO = Path(__file__).parent / "demo_data" / "scenario.json"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PATH_MINUTES = 26 * 60

# archetype -> (closed trades, win probability, win roi range, loss roi range, median hold s, buy size $)
ARCHETYPES = {
    "elite":    (26, 0.73, (0.35, 2.6), (-0.65, -0.15), 3.2 * 3600, 2000),
    "good":     (16, 0.62, (0.25, 1.6), (-0.60, -0.15), 1.5 * 3600, 1100),
    "newbie":   (4, 1.00, (0.40, 1.8), (-0.50, -0.20), 2.0 * 3600, 650),
    "mediocre": (30, 0.44, (0.15, 0.8), (-0.70, -0.20), 1.0 * 3600, 800),
    "bot":      (120, 0.55, (0.01, 0.06), (-0.06, -0.01), 22, 500),
    "sniper":   (18, 0.70, (0.30, 1.4), (-0.60, -0.20), 420, 900),
    "wash":     (20, 0.50, (0.00, 0.01), (-0.01, 0.00), 120, 1500),
    "fresh":    (6, 0.83, (0.50, 1.5), (-0.40, -0.20), 1800, 1400),
}
# how a coin behaves after a wallet of this quality buys it: the built-in (synthetic) edge
PATH_ODDS = {
    "elite":    {"runner": 0.22, "grind": 0.22, "pumpdump": 0.17, "spike": 0.09, "bleed": 0.19, "rug": 0.11},
    "good":     {"runner": 0.15, "grind": 0.18, "pumpdump": 0.19, "spike": 0.10, "bleed": 0.24, "rug": 0.14},
    "weak":     {"runner": 0.08, "grind": 0.12, "pumpdump": 0.20, "spike": 0.10, "bleed": 0.30, "rug": 0.20},
}
CALLER_ODDS = {"good": (0.68, 1.35), "mid": (0.52, 1.08), "bad": (0.36, 0.86)}   # (hit rate at 1h, typical multiple)


def _address(chain: str, tag: str) -> str:
    h = hashlib.sha256(f"sms-demo:{chain}:{tag}".encode()).digest()
    if chain == "solana":
        return "".join(B58[b % 58] for b in h) + "".join(B58[b % 58] for b in h[:12])
    return "0x" + h.hex()[:40]


def envelope(kind: str, p: dict, m: float) -> float:
    """Price multiple vs the first buy, `m` minutes after it. Before it: a gentle run-up."""
    if m < 0:
        return 0.7 + 0.3 * math.exp(m / 30)
    if kind == "runner":
        if m <= p["m_peak"]:
            return 1 + (p["peak"] - 1) * (m / p["m_peak"]) ** 0.8
        return p["end"] + (p["peak"] - p["end"]) * math.exp(-(m - p["m_peak"]) / 300)
    if kind == "grind":
        return 1 + (p["end"] - 1) * (1 - math.exp(-m / 400))
    if kind == "pumpdump":
        if m <= p["m_peak"]:
            return 1 + (p["peak"] - 1) * m / p["m_peak"]
        return p["end"] + (p["peak"] - p["end"]) * math.exp(-(m - p["m_peak"]) / 40)
    if kind == "spike":
        if m <= p["m_peak"]:
            return 1 + (p["peak"] - 1) * m / p["m_peak"]
        return p["settle"] + (p["peak"] - p["settle"]) * math.exp(-(m - p["m_peak"]) / 3)
    if kind == "bleed":
        return p["end"] + (1 - p["end"]) * math.exp(-m / 240)
    if kind == "rug":
        if m <= p["m_rug"]:
            return 1 + (p["pre"] - 1) * m / p["m_rug"]
        return max(0.04, p["pre"] * math.exp(-(m - p["m_rug"]) * 1.4))
    return 1.0   # flat


def random_params(kind: str, rng: random.Random) -> dict:
    if kind == "runner":
        peak = rng.uniform(2.6, 6.5)
        return {"peak": peak, "m_peak": rng.uniform(80, 240), "end": rng.uniform(1.3, peak * 0.6)}
    if kind == "grind":
        return {"end": rng.uniform(1.25, 2.0)}
    if kind == "pumpdump":
        return {"peak": rng.uniform(1.6, 3.0), "m_peak": rng.uniform(10, 32), "end": rng.uniform(0.3, 0.65)}
    if kind == "spike":
        return {"peak": rng.uniform(2.2, 4.0), "m_peak": rng.uniform(2, 4), "settle": rng.uniform(0.95, 1.3)}
    if kind == "bleed":
        return {"end": rng.uniform(0.3, 0.75)}
    if kind == "rug":
        return {"m_rug": rng.uniform(12, 95), "pre": rng.uniform(1.0, 1.4)}
    return {}


class DemoToken:
    def __init__(self, chain, symbol, name, launchpad, kind, params, mcap, first_buy_ts, age_min, seed, risks=None):
        self.chain, self.symbol, self.name, self.launchpad = chain, symbol, name, launchpad
        self.kind, self.params, self.mcap0 = kind, params, mcap
        self.first_buy_ts = first_buy_ts
        self.lead = int(min(age_min, 180))                # minutes of candles before the first buy
        self.created_ts = first_buy_ts - int(age_min * 60)
        self.start_ts = first_buy_ts - self.lead * 60
        self.address = _address(chain, f"token:{symbol}:{first_buy_ts}")
        self.pool = _address(chain, f"pool:{symbol}:{first_buy_ts}")
        self.risks = risks or []
        self.seed = seed
        self._closes: list[float] | None = None
        self.p0 = 10 ** random.Random(seed).uniform(-6.2, -3.2)
        self.dead_after = None
        if kind == "rug":
            self.dead_after = self.lead + int(params["m_rug"]) + 8       # nobody trades a rugged pool

    def closes(self) -> list[float]:
        if self._closes is None:
            rng = random.Random(self.seed + 1)
            noise, out = 0.0, []
            for i in range(self.lead + PATH_MINUTES + 1):
                noise = 0.9 * noise + rng.gauss(0, 0.018)
                out.append(self.p0 * envelope(self.kind, self.params, i - self.lead) * math.exp(noise))
            # the first buy happens at exactly p0-ish; pin it so entry maths is clean
            self._closes = out
        return self._closes

    def price(self, ts: int) -> float | None:
        i = (ts - self.start_ts) // 60
        if i < 0:
            return None
        closes = self.closes()
        if self.dead_after is not None:
            i = min(i, self.dead_after)
        return closes[min(i, len(closes) - 1)]

    def candles(self, start: int, end: int) -> list[list]:
        closes = self.closes()
        i0 = max(0, (start - self.start_ts) // 60)
        i1 = min(len(closes) - 1, (end - self.start_ts) // 60)
        if self.dead_after is not None:
            i1 = min(i1, self.dead_after)
        rng = random.Random(self.seed + 2 + i0)
        out = []
        for i in range(i0, i1 + 1):
            o = closes[i - 1] if i else closes[0]
            c = closes[i]
            wick = abs(rng.gauss(0, 0.006))
            out.append([self.start_ts + i * 60, o, max(o, c) * (1 + wick), min(o, c) * (1 - wick), c,
                        round(rng.uniform(200, 9000), 2)])
        return out


class DemoHub:
    demo = True

    def __init__(self, scenario: dict | None = None):
        sc = scenario or json.loads(SCENARIO.read_text(encoding="utf-8"))
        self.sc = sc
        self.end = int(datetime.fromisoformat(sc["end"]).astimezone(timezone.utc).timestamp())
        self.t = self.end
        self.rng = random.Random(sc["seed"])
        self.wallets = {w["id"]: {**w, "address": _address(w["chain"], f"wallet:{w['id']}")} for w in sc["wallets"]}
        self.by_address = {w["address"]: w for w in self.wallets.values()}
        self.tokens: dict[str, DemoToken] = {}
        self.history: dict[str, list[Trade]] = {w["address"]: [] for w in self.wallets.values()}
        self.live: list[Trade] = []
        self.calls_by_token: dict[str, list[Call]] = {}
        self.caller_hist: dict[str, list[Call]] = {}
        self._name_i: dict[str, int] = {}
        self._build_history()
        self._build_callers()
        self._build_live()
        self.live.sort(key=lambda t: t.ts)
        self.start = min(t.ts for t in self.live) - 60
        self._trend = self._build_trending()

    # ------------------------------------------------------------- the world

    def _next_name(self, narrative: str) -> str:
        pool = self.sc["names"][narrative]
        i = self._name_i.get(narrative, 0)
        self._name_i[narrative] = i + 1
        base = pool[i % len(pool)]
        # when a pool runs out, do what memecoins do: Baby X, Super X, 小X
        round_ = i // len(pool)
        if round_ == 0:
            return base
        chinese = any("\u4e00" <= ch <= "\u9fff" for ch in base)
        prefixes = ("小", "大", "超级", "新") if chinese else ("Baby ", "Super ", "Mega ", "Lil ")
        return prefixes[(round_ - 1) % len(prefixes)] + base

    def _build_history(self) -> None:
        """Thirty days of closed trades per wallet, shaped by its archetype."""
        for w in self.wallets.values():
            n, p_win, win, loss, hold, size = ARCHETYPES[w["archetype"]]
            span = 86400 if w["archetype"] == "fresh" else 29 * 86400
            for k in range(n):
                ts = self.end - 4 * 3600 - int(self.rng.uniform(0.02, 1) * span)
                roi = self.rng.uniform(*win) if self.rng.random() < p_win else self.rng.uniform(*loss)
                held = max(8, int(hold * math.exp(self.rng.gauss(0, 0.5))))
                usd = size * (1.0 if w["archetype"] == "bot" else self.rng.uniform(0.6, 1.6))
                narrative = self.rng.choice(w["home"])
                symbol = self.rng.choice(self.sc["names"][narrative]).replace(" ", "").upper()
                price = 10 ** self.rng.uniform(-6, -3)
                token = _address(w["chain"], f"hist:{w['id']}:{k}")
                created = ts - (1 if w["archetype"] == "sniper" else int(self.rng.uniform(120, 3 * 86400)))
                common = dict(chain=w["chain"], wallet=w["address"], token=token, symbol=symbol,
                              token_amount=usd / price, token_created_ts=created, source="demo")
                self.history[w["address"]] += [
                    Trade(side="buy", ts=ts, usd=round(usd, 2), price_usd=price, tx=f"demo-h-{w['id']}-{k}-b", **common),
                    Trade(side="sell", ts=ts + held, usd=round(usd * (1 + roi), 2), price_usd=price * (1 + roi),
                          tx=f"demo-h-{w['id']}-{k}-s", **common)]

    def _build_callers(self) -> None:
        for c in self.sc["callers"]:
            p_hit, typical = CALLER_ODDS[c["quality"]]
            hist = []
            for k in range(c["n"]):
                ts = self.end - 2 * 86400 - int(self.rng.uniform(0, 18) * 86400)
                hit = self.rng.random() < p_hit
                x1h = self.rng.uniform(1.02, typical * 1.5) if hit else self.rng.uniform(0.45, 0.98)
                hist.append(Call(caller=c["handle"], chain="solana", token=_address("solana", f"call:{c['handle']}:{k}"),
                                 ts=ts, price_usd=1e-5, followers=c["followers"],
                                 x15m=round(1 + (x1h - 1) * self.rng.uniform(0.3, 0.8), 3), x1h=round(x1h, 3),
                                 x24h=round(max(0.05, x1h * self.rng.uniform(0.5, 1.6)), 3)))
            self.caller_hist[c["handle"]] = sorted(hist, key=lambda x: x.ts)

    def _add_live_buy(self, w: dict, tok: DemoToken, ts: int, usd: float, sell: bool = True) -> None:
        price = tok.price(ts)
        common = dict(chain=tok.chain, wallet=w["address"], token=tok.address, symbol=tok.symbol,
                      token_created_ts=tok.created_ts, source="demo")
        amount = usd / price
        self.live.append(Trade(side="buy", ts=ts, usd=round(usd, 2), price_usd=price, token_amount=amount,
                               tx=f"demo-{tok.symbol}-{w['id']}-{ts}-b", **common))
        if sell:
            _, _, _, _, hold, _ = ARCHETYPES[w["archetype"]]
            out_ts = ts + max(300, int(hold * math.exp(self.rng.gauss(0, 0.4))))
            out_price = tok.price(out_ts)
            self.live.append(Trade(side="sell", ts=out_ts, usd=round(amount * out_price, 2), price_usd=out_price,
                                   token_amount=amount, tx=f"demo-{tok.symbol}-{w['id']}-{ts}-s", **common))

    def _build_live(self) -> None:
        """The simulated feed: ten days of buys that get alerts, then the hand-written last three hours."""
        sc, rng = self.sc, self.rng
        pool = [w for w in self.wallets.values() if w["weight"] > 0]
        weights = [w["weight"] for w in pool]
        callers = [c["handle"] for c in sc["callers"]]
        span = sc["history_days"] * 86400
        times = sorted(self.end - 4 * 3600 - int(rng.uniform(0, 1) * (span - 4 * 3600)) for _ in range(sc["history_buys"]))
        for i, ts in enumerate(times):
            w = rng.choices(pool, weights)[0]
            tier = w["archetype"] if w["archetype"] in ("elite", "good") else "weak"
            kind = rng.choices(list(PATH_ODDS[tier]), list(PATH_ODDS[tier].values()))[0]
            narrative = rng.choice(w["home"])
            name = self._next_name(narrative)
            symbol = name.replace(" ", "").upper()
            launchpad = {"solana": "pump.fun", "bsc": "four.meme" if rng.random() < 0.8 else "", "base": ""}[w["chain"]]
            age = 0.02 if w["archetype"] == "sniper" else rng.choice([3, 8, 20, 45, 120, 600, 2000])
            tok = DemoToken(w["chain"], symbol, name, launchpad, kind,
                            random_params(kind, rng), rng.uniform(40_000, 900_000), ts, age, sc["seed"] + 100 + i,
                            risks=["top 10 holders own 64%"] if kind == "rug" and rng.random() < 0.5 else None)
            self.tokens[tok.address] = tok
            _, _, _, _, _, size = ARCHETYPES[w["archetype"]]
            self._add_live_buy(w, tok, ts, size * (1 if w["archetype"] == "bot" else rng.uniform(0.7, 2.4)))
            # sometimes a second good wallet on the same chain follows within minutes: a cluster
            if rng.random() < 0.18:
                mates = [m for m in pool if m["chain"] == w["chain"] and m["id"] != w["id"] and m["archetype"] in ("elite", "good")]
                if mates:
                    m = rng.choice(mates)
                    self._add_live_buy(m, tok, ts + rng.randint(120, 1200), ARCHETYPES[m["archetype"]][5] * rng.uniform(0.7, 1.8))
            if rng.random() < 0.35:
                handle = rng.choice(callers)
                cts = ts + rng.randint(-300, 900)
                self._add_call(tok, handle, cts)

        for j, f in enumerate(sc["featured"]):
            first = self.end - max(b["min_ago"] for b in f["buys"]) * 60
            tok = DemoToken(f["chain"], f["symbol"], f["name"], f["launchpad"], f["path"], f["params"], f["mcap"],
                            first, f["age_min"], sc["seed"] + 5000 + j, risks=f.get("risks"))
            self.tokens[tok.address] = tok
            for b in f["buys"]:
                self._add_live_buy(self.wallets[b["wallet"]], tok, self.end - b["min_ago"] * 60, b["usd"], sell=False)
            for c in f["calls"]:
                self._add_call(tok, c["caller"], self.end - c["min_ago"] * 60)

    def _add_call(self, tok: DemoToken, handle: str, ts: int) -> None:
        followers = next(c["followers"] for c in self.sc["callers"] if c["handle"] == handle)
        self.calls_by_token.setdefault(tok.address, []).append(
            Call(caller=handle, chain=tok.chain, token=tok.address, ts=ts, price_usd=tok.price(ts), followers=followers,
                 text=f"${tok.symbol} looks interesting"))

    def _build_trending(self) -> dict[str, list[Token]]:
        """Two trending lists whose mix differs, so each narrative lands in a different state."""
        featured = {}
        for f in self.sc["featured"]:
            from .grading.narrative import classify
            featured.setdefault(classify(f["name"], f["symbol"])[0], []).append(f)
        out = {}
        for window, mix in self.sc["trending"].items():
            rows, rng = [], random.Random(self.sc["seed"] + len(window))
            for narrative, count in mix.items():
                names = [f["name"] for f in featured.get(narrative, [])] if window == "now" else []
                names += [n for n in self.sc["names"][narrative] if n not in names]
                for k, name in enumerate(names[:count]):
                    chain = "bsc" if narrative in ("chinese", "binance") else "base" if k % 5 == 4 else "solana"
                    rows.append(Token(chain=chain, address=_address(chain, f"trend:{name}"),
                                      symbol=name.replace(" ", "").upper(), name=name,
                                      volume_h1=round(rng.uniform(20_000, 900_000)), change_h1=round(rng.uniform(-30, 160), 1)))
            out[window] = rows
        return out

    # --------------------------------------------------------- hub interface

    def now(self) -> int:
        return self.t

    def status(self) -> list[dict]:
        return [{"source": "demo data (synthetic)", "on": True, "needs": "nothing", "requests": 0, "failures": 0, "last_error": ""}]

    def recent_trades(self, since: int) -> list[Trade]:
        return [t for t in self.live if since < t.ts <= self.t]

    def wallet_trades(self, chain: str, wallet: str, since: int) -> list[Trade]:
        mine = self.history.get(wallet, []) + [t for t in self.live if t.wallet == wallet]
        return sorted((t for t in mine if since <= t.ts <= self.t), key=lambda t: t.ts)

    def wallet_meta(self, chain: str, wallet: str) -> dict:
        w = self.by_address.get(wallet)
        if not w:
            return {}
        meta = {"name": w["label"], "tags": []}
        if w["archetype"] == "fresh":
            meta.update(first_funded_ts=self.end - 86400, cluster_size=3)
        return meta

    def token(self, chain: str, address: str) -> Token | None:
        tok = self.tokens.get(address)
        if not tok:
            return None
        price = tok.price(self.t)
        ref = tok.price(tok.first_buy_ts)
        return Token(chain=tok.chain, address=tok.address, symbol=tok.symbol, name=tok.name, pool=tok.pool,
                     dex="demo", launchpad=tok.launchpad, price_usd=price,
                     mcap_usd=round(tok.mcap0 * price / ref) if price and ref else None,
                     liquidity_usd=round(tok.mcap0 * 0.18), created_ts=tok.created_ts)

    def candles(self, chain: str, token: Token, start: int, end: int) -> list[list]:
        tok = self.tokens.get(token.address)
        return tok.candles(start, min(end, self.t)) if tok else []

    def safety(self, chain: str, address: str) -> dict | None:
        tok = self.tokens.get(address)
        return {"source": "demo", "risks": list(tok.risks)} if tok else None

    def trending(self, chain: str) -> dict[str, list[Token]]:
        return {w: [t for t in rows if t.chain == chain] for w, rows in self._trend.items()}

    def narrative_posts(self) -> dict:
        return {}

    def categories(self) -> dict:
        return dict(self.sc["categories"])

    def calls(self, chain: str, token: Token) -> list[Call]:
        return [c for c in self.calls_by_token.get(token.address, []) if c.ts <= self.t]

    def caller_history(self, caller: str) -> list[Call]:
        return [c for c in self.caller_hist.get(caller, []) if c.ts <= self.t]

    # ------------------------------------------------------------ simulation

    def ticks(self) -> list[int]:
        """Moments the simulated scanner wakes up: shortly after each buy, then the end."""
        out, last = [], 0
        for t in self.live:
            if t.side == "buy" and t.ts + 50 - last >= 60:
                last = t.ts + 50
                out.append(last)
        return [x for x in out if x < self.end] + [self.end]


def run(settings, ledger, store, deliverers=(), on_tick=None) -> dict:
    """Play the whole scenario through the real pipeline. Returns a small summary."""
    from .pipeline import Pipeline
    from .scoring import score_ledger

    hub = DemoHub()
    pipe = Pipeline(hub, settings, store, ledger, deliverers)
    store.put("cursor", hub.start, hub.start)
    alerts, day = [], None
    for t in hub.ticks():
        hub.t = t
        today = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        if day and today != day and len(ledger):
            ledger.anchor(t, day)            # one anchor line per finished day
        day = today
        alerts += pipe.run_once()
        score_ledger(hub, ledger)
        if on_tick:
            on_tick(hub, t)
    return {"hub": hub, "pipeline": pipe, "alerts": alerts}
