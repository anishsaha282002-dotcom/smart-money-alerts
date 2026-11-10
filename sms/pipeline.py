"""One scan: new buys -> grade the wallet -> build the alert -> write it to the ledger -> deliver.

The order matters for the public record: the alert is written to the ledger *before* it is
delivered anywhere, so nothing can be sent that is not on the record.
"""
from __future__ import annotations

import logging

from . import story
from .config import Settings
from .grading import baserate, copycheck, narrative
from .grading.caller import grade_callers
from .grading.wallet import grade_wallet
from .ledger import Ledger
from .models import Token, Trade, WalletGrade, grade_rank, short
from .signals import SM_BUYING, SM_SELLING, SM_WINDOW_S, cluster_wallets, kol_buy, shill_block, soft_sell
from .store import Store
from .util import duration, usd

log = logging.getLogger(__name__)
GRADE_TTL = 1800
COPY_TTL = 12 * 3600


class Pipeline:
    def __init__(self, hub, settings: Settings, store: Store, ledger: Ledger, deliverers: tuple = ()):
        self.hub, self.s, self.store, self.ledger = hub, settings, store, ledger
        self.deliverers = deliverers
        self._board: dict | None = None

    # --------------------------------------------------------------- grading

    def grade(self, chain: str, wallet: str, refresh: bool = False) -> tuple[WalletGrade, list[Trade]]:
        now = self.hub.now()
        since = now - self.s.lookback_days * 86400
        trades = self.hub.wallet_trades(chain, wallet, since)
        key = f"grade:{chain}:{wallet}"
        cached = None if refresh else self.store.get(key, max_age=GRADE_TTL, now=now)
        if cached:
            return WalletGrade(**cached["grade"]), trades
        meta = self.hub.wallet_meta(chain, wallet)
        g = grade_wallet(trades, now, meta, days=self.s.lookback_days, prior=self.s.prior_trades,
                         small_sample=self.s.small_sample, cap_below=self.s.cap_below)
        seen = {}
        for t in trades:
            if t.symbol:
                seen.setdefault(t.token, t.symbol)
        g.narratives = sorted({narrative.classify(symbol=s)[0] for s in seen.values()})
        self.store.put(key, {"grade": g.to_dict(), "chain": chain, "wallet": wallet,
                             "label": meta.get("name") or "", "twitter": meta.get("twitter") or ""}, now)
        return g, trades

    def copy_history(self, chain: str, wallet: str, trades: list[Trade]) -> dict | None:
        """Median copy check over the wallet's most recent buys whose 4h window has closed."""
        now = self.hub.now()
        key = f"copy:{chain}:{wallet}"
        cached = self.store.get(key, max_age=COPY_TTL, now=now)
        if cached is not None:
            return cached or None
        first_buy: dict[str, Trade] = {}
        for t in sorted(trades, key=lambda t: t.ts):
            if t.side == "buy" and t.ts <= now - copycheck.WINDOW:
                first_buy.setdefault(t.token, t)
        checks = []
        for t in sorted(first_buy.values(), key=lambda t: -t.ts)[: self.s.copy_history_buys]:
            token = self.hub.token(chain, t.token) or Token(chain=chain, address=t.token)
            candles = self.hub.candles(chain, token, t.ts - 120, t.ts + copycheck.WINDOW)
            p0 = t.price_usd or copycheck.price_at(candles, t.ts)
            check = copycheck.copy_check(candles, t.ts, p0)
            if check:
                check.pop("spark", None)
                checks.append(check)
        summary = copycheck.summarize(checks)
        self.store.put(key, summary or {}, now)
        return summary

    def board(self) -> dict:
        """Narrative momentum across every configured chain, once per scan."""
        if self._board is None:
            now_list, base_list = [], []
            for chain in self.s.chains:
                lists = self.hub.trending(chain)
                now_list += lists.get("now", [])
                base_list += lists.get("base", [])
            reads = narrative.momentum(now_list, base_list, self.hub.narrative_posts(), self.hub.categories())
            self._board = {k: r.to_dict() for k, r in reads.items()}
            self.store.put("narratives", self._board, self.hub.now())
        return self._board

    # ---------------------------------------------------------------- alerts

    def cluster(self, buy: Trade) -> list[dict]:
        """Other wallets we already graded well that bought the same coin just before this one."""
        out, seen = [], {buy.wallet}
        for t in self.store.token_buys(buy.chain, buy.token, buy.ts - self.s.cluster_window_min * 60, buy.ts):
            if t.wallet in seen:
                continue
            seen.add(t.wallet)
            cached = self.store.get(f"grade:{buy.chain}:{t.wallet}")
            if cached and cached["grade"]["grade"] in ("A", "B"):
                out.append({"wallet": t.wallet, "grade": cached["grade"]["grade"], "usd": round(t.usd, 2), "ts": t.ts})
        return out

    def reasons(self, buy: Trade, token: Token, g: WalletGrade, cluster: list[dict], read: dict, callers,
                age_s: int | None, size_x: float | None, mcap: float | None) -> list[dict]:
        out = []
        if cluster:
            grades = ", ".join(sorted(c["grade"] for c in cluster))
            out.append({"kind": "cluster", "text": f"Wallet cluster bought: {len(cluster)} other graded wallet"
                        f"{'s' if len(cluster) != 1 else ''} ({grades}) bought it in the "
                        f"{self.s.cluster_window_min} minutes before."})
        key = read["key"]
        if g.narratives and key not in g.narratives and key != "other" and g.n_closed >= 3:
            out.append({"kind": "new-narrative", "text": f"First buy in the {read['label']} narrative for this wallet "
                        f"in {self.s.lookback_days} days."})
        if read["state"] in ("new", "rising") and key != "other":
            out.append({"kind": "narrative", "text": f"The {read['label']} narrative is {read['state']} right now."})
        if age_s is not None and age_s < 3600:
            out.append({"kind": "early", "text": f"Early: bought {duration(age_s)} after launch."})
        elif mcap is not None and mcap < 250_000:
            out.append({"kind": "early", "text": f"Small: only {usd(mcap)} market cap at the time of the buy."})
        if size_x is not None and size_x >= 2:
            out.append({"kind": "size", "text": f"Conviction: {size_x:.1f}× its usual buy size."})
        best = next((c for c in callers.callers if c.get("grade") in ("A", "B")), None)
        if best:
            out.append({"kind": "caller", "text": f"Caller mentioned: @{best['caller']} ({best['grade']})."})
        return out

    def build_alert(self, buy: Trade, g: WalletGrade, trades: list[Trade], token: Token, now: int) -> dict:
        meta = self.hub.wallet_meta(buy.chain, buy.wallet)
        mentions = self.hub.calls(buy.chain, token)
        histories = {m.caller: self.hub.caller_history(m.caller) for m in mentions}
        callers = grade_callers(mentions, histories, self.s.min_caller_followers,
                                leaderboard=self.leaderboard())

        tags = narrative.classify(token.name, token.symbol, token.description)
        board = self.board()
        read = dict(board.get(tags[0]) or narrative.NarrativeRead(tags[0], narrative.label(tags[0]), "unknown").to_dict())
        read["tags"] = tags

        created = token.created_ts or buy.token_created_ts
        age_s = buy.ts - created if created and buy.ts >= created else None
        size_x = round(buy.usd / g.median_buy_usd, 2) if g.median_buy_usd else None
        price = buy.price_usd or token.price_usd
        entry = token.price_usd or price
        mcap = token.mcap_usd
        cluster = self.cluster(buy)
        safety = self.hub.safety(buy.chain, token.address) if self.s.safety_checks else None
        tracked = self.store.token_buys(buy.chain, buy.token, buy.ts - SM_WINDOW_S, buy.ts) + [buy]
        sm = cluster_wallets(tracked, buy.chain, buy.token, buy.ts, self.s.wallet_book)
        kol = kol_buy(buy.chain, buy.wallet, self.s.wallet_book)

        alert = {
            "id": self.ledger.next_alert_id(),
            "chain": buy.chain,
            "token": {"address": token.address, "symbol": token.symbol or buy.symbol, "name": token.name,
                      "pool": token.pool, "dex": token.dex, "launchpad": token.launchpad, "created_ts": created},
            "wallet": {"address": buy.wallet, "label": meta.get("name") or "", "twitter": meta.get("twitter") or ""},
            "buy": {"ts": buy.ts, "usd": round(buy.usd, 2), "price": price, "tx": buy.tx, "age_s": age_s, "size_x": size_x},
            "entry_price": entry,
            "mcap_usd": mcap,
            "liquidity_usd": token.liquidity_usd,
            "grades": {"wallet": g.to_dict(), "caller": callers.to_dict(), "narrative": read},
            "copy_hist": self.copy_history(buy.chain, buy.wallet, trades),
            "cluster": cluster,
            "sm_cluster": sm,
            "kol": bool(kol),
            "activity": SM_BUYING,
            "reasons": self.reasons(buy, token, g, cluster, read, callers, age_s, size_x, mcap),
            "safety": safety,
            "demo": bool(getattr(self.hub, "demo", False)),
            "_mentions": mentions,
        }
        if sm:
            names = ", ".join(x["name"] or short(x["wallet"]) for x in sm[:4])
            alert["reasons"].append({"kind": "sm-cluster",
                                     "text": f"Wallet cluster bought: {len(sm)} tracked wallets bought it within the hour ({names})."})
        if kol:
            alert["reasons"].append({"kind": "kol", "text": f"KOL bought: {kol.get('name') or short(buy.wallet)}."})
        alert["base_rate"] = baserate.lookup(alert, self.baserates(), leaders=self.leader_wallets())
        alert["story"] = story.reword(story.render(alert, self.s.cap_below), self.s)
        return alert

    def leader_wallets(self) -> set:
        if getattr(self, "_leaders", None) is None:
            from .sources.pumpfun_callouts import load_snapshot
            snap = load_snapshot()
            self._leaders = baserate.leader_wallets(snap) if snap.get("loaded") else set()
        return self._leaders

    def baserates(self) -> dict:
        if getattr(self, "_rates", None) is None:
            self._rates = baserate.load()
        return self._rates

    def leaderboard(self) -> dict:
        if getattr(self, "_lb", None) is None:
            from .sources.pumpfun_callouts import index_callers, load_snapshot
            snap = load_snapshot()
            self._lb = index_callers(snap) if snap.get("loaded") else {}
        return self._lb

    # ------------------------------------------------------------------- run

    def run_once(self) -> list[dict]:
        now = self.hub.now()
        self._board = None
        since = self.store.get("cursor")
        if since is None:
            since = now - 900          # a first run does not alert on old history
        trades = self.hub.recent_trades(since)
        self.store.add_trades(trades)
        buys = sorted((t for t in trades if t.side == "buy" and since < t.ts <= now and t.usd >= self.s.min_buy_usd),
                      key=lambda t: t.ts)
        alerts = []
        resume_at = None
        for buy in buys:
            if len(alerts) >= self.s.max_alerts_per_run:
                resume_at = buy.ts - 1         # the next scan starts here, so nothing is silently dropped
                log.info("alert cap for this scan reached; the remaining buys are picked up by the next scan")
                break
            if self.store.alerted_since(buy.chain, buy.wallet, buy.token, now - int(self.s.cooldown_hours * 3600)):
                continue
            g, wallet_trades = self.grade(buy.chain, buy.wallet)
            if grade_rank(g.grade) > grade_rank(self.s.min_grade):
                continue
            token = self.hub.token(buy.chain, buy.token) or Token(chain=buy.chain, address=buy.token, symbol=buy.symbol)
            if not (token.price_usd or buy.price_usd):
                log.info("skip %s: no price to anchor the record to", short(buy.token))
                continue
            alert = self.build_alert(buy, g, wallet_trades, token, now)
            mentions = alert.pop("_mentions", [])
            block = shill_block(mentions, token.organic_score, g.flags)
            if block:
                log.info("skip %s: %s", short(buy.token), block)
                continue
            entry = self.ledger.append("alert", now, alert)       # on the record first
            self.store.mark_alerted(buy.chain, buy.wallet, buy.token, now)
            for d in self.deliverers:
                d.send(entry)
            alerts.append(entry)
        self._record_sells(trades, since, now)
        self.store.put("cursor", resume_at if resume_at is not None else now, now)
        self.board()
        return alerts

    def _record_sells(self, trades: list[Trade], since: int, now: int) -> None:
        """Record smart-money selling. This is an observation, not a trade instruction."""
        from . import ADVICE
        for sell in sorted((t for t in trades if t.side == "sell" and since < t.ts <= now), key=lambda t: t.ts):
            info = soft_sell(sell, self.s.wallet_book)
            if not info:
                continue
            if self.store.alerted_since(sell.chain, sell.wallet, sell.token, now - int(self.s.cooldown_hours * 3600)):
                continue
            token = self.hub.token(sell.chain, sell.token) or Token(chain=sell.chain, address=sell.token, symbol=sell.symbol)
            meta = self.hub.wallet_meta(sell.chain, sell.wallet)
            n = len(self.ledger.entries(SM_SELLING)) + 1
            symbol = token.symbol or short(sell.token)
            text = f"Smart-money selling ${symbol} — {info['text']}. {ADVICE}"
            payload = {
                "id": f"s-{n:05d}", "activity": SM_SELLING, "chain": sell.chain,
                "token": {"address": token.address, "symbol": token.symbol or sell.symbol, "name": token.name,
                          "pool": token.pool, "dex": token.dex, "launchpad": token.launchpad},
                "wallet": {"address": sell.wallet, "label": meta.get("name") or info["name"], "twitter": meta.get("twitter") or ""},
                "buy": {"ts": sell.ts, "usd": round(sell.usd, 2), "price": sell.price_usd, "tx": sell.tx,
                        "age_s": None, "size_x": None},
                "entry_price": sell.price_usd or token.price_usd, "mcap_usd": token.mcap_usd,
                "liquidity_usd": token.liquidity_usd,
                "grades": {"wallet": {"grade": None, "score": None, "n_closed": 0, "flags": [], "days": self.s.lookback_days,
                                      "last10_wins": 0, "last10_n": 0, "pnl_usd": 0, "small_sample": False},
                           "caller": {"grade": None, "n_callers": 0, "callers": [], "note": ""},
                           "narrative": {"key": "other", "label": "No clear theme", "state": "unknown"}},
                "copy_hist": None, "cluster": [], "sm_cluster": [], "kol": info["kind"] == "kol",
                "reasons": [{"kind": SM_SELLING, "text": info["text"]}],
                "safety": None, "demo": bool(getattr(self.hub, "demo", False)), "story": text,
            }
            self.ledger.append(SM_SELLING, now, payload)
            self.store.mark_alerted(sell.chain, sell.wallet, sell.token, now)
