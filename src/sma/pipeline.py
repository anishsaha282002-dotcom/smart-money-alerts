"""Orchestration: discover buys -> grade wallet -> copy check -> callers -> narrative -> story -> ledger."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from . import latecheck, story
from .config import GRADE_ORDER, HORIZON_S, resolve
from .grading import caller as callerg
from .grading import narrative as narr
from .grading.wallet import grade_wallet
from .ledger import Ledger
from .notify import deliver
from .util import fnum, median, norm_addr, utc_iso


def _grade(hub, cfg, chain, wallet, now_ts, allow_fetch=True):
    g = cfg["grading"]
    trades, src = hub.wallet_trades(chain, wallet, now_ts - (g["window_days"] + 2) * 86400, now_ts, allow_fetch)
    wg, positions = grade_wallet(wallet, chain, trades, now_ts, window_days=g["window_days"], shrink_k=g["shrink_k"],
                                 low_sample=g["low_sample"], small_sample=g["small_sample"],
                                 min_closed=cfg["alerts"]["min_closed_trades"], closed_fraction=g["closed_fraction"],
                                 data_source=src)
    return wg, positions, trades


def late_history(hub, cfg, chain, positions, exclude_token=None):
    closed = sorted([p for p in positions if p.closed and p.token != exclude_token], key=lambda p: -p.close_ts)
    closed = closed[: cfg["grading"]["late_check_max_trades"]]
    if closed:
        hub.prefetch_tokens(chain, [p.token for p in closed])
    reps = []
    for p in closed:
        info = hub.token_info(chain, p.token)
        if not info or not info.get("pool"):
            continue
        candles = hub.ohlcv(chain, info["pool"], p.open_ts - 120, max(p.close_ts, p.open_ts + 1800) + 120)
        if not candles:
            continue
        reps.append(latecheck.replay_position(candles, p.open_ts, p.close_ts, p.first_buy_price_usd))
    return latecheck.summarize(reps)


def narratives(hub, store, now_ts):
    ranked, tok_map = narr.cluster_and_score(hub.narrative_tokens(), now_ts)
    for n in ranked:
        n["status"], n["why"] = narr.label(n, store.narrative_history(n["narrative"], now_ts))
    store.save_narratives(now_ts, ranked[:60])
    return ranked, tok_map


def pick_narrative(ranked, tok_map, chain, token, info):
    names = set(tok_map.get((chain, norm_addr(chain, token)), []))
    if not names and info:
        hits, _ = narr.narratives_for(info.get("name"), info.get("symbol"))
        names = hits
    cands = [n for n in ranked if n["narrative"] in names]
    if not cands:
        return None
    pri = {"HOT": 4, "RISING": 3, "NEW": 2, "FLAT": 1, "FADING": 0}
    best = max(cands, key=lambda n: (pri.get(n["status"], 0), n["score"]))
    return {k: best[k] for k in ("narrative", "status", "score", "n_tokens", "vol_h1", "why")}


def _value_usd(b, natives):
    if b.get("usd"):
        return fnum(b["usd"])
    if b.get("value_unit") == "usd":
        return fnum(b.get("value"))
    px = natives.get(b.get("value_unit") or "")
    return fnum(b.get("value")) * px if px else None


def run(hub, store, cfg, now_ts, *, deliver_enabled=True, log=print):
    a_cfg, d_cfg = cfg["alerts"], cfg["discovery"]
    ledger = Ledger(resolve(cfg, "ledger"))
    callers_j = json.loads((resolve(cfg, "callers")).read_text(encoding="utf-8"))
    callers = callerg.load_callers(callers_j)
    caller_tracked = store.caller_stats()
    natives = hub.native_prices() or {}
    since = now_ts - a_cfg["lookback_minutes"] * 60
    summary = {"now": utc_iso(now_ts), "alerts": [], "skipped": defaultdict(int), "graded_wallets": 0}

    ranked, tok_map = narratives(hub, store, now_ts)
    summary["narratives_top"] = [(n["narrative"], n["status"], n["score"]) for n in ranked[:8]]

    buys = hub.recent_buys(since, now_ts)
    summary["buys_seen"] = len(buys)
    recent = {(r["chain"], r["wallet"], r["token"]) for r in ledger.alerts()
              if now_ts - r["created_ts"] < a_cfg["dedupe_hours"] * 3600}
    # strongest candidates first: tracked / GMGN-tagged, then size
    buys.sort(key=lambda b: (not b.get("tracked"), not b.get("source", "").startswith("gmgn"), -(_value_usd(b, natives) or 0)))
    grades, new_grades = {}, 0
    first = {}
    for b in buys:
        k = (b["chain"], b["wallet"], b["token"])
        if k not in first or b["ts"] < first[k]["ts"]:
            first[k] = b
    by_token = defaultdict(list)
    for b in first.values():
        by_token[(b["chain"], b["token"])].append(b)
    min_rank = GRADE_ORDER[a_cfg["min_wallet_grade"]]
    candidates = []
    for k, b in first.items():
        usd = _value_usd(b, natives)
        if usd is not None and usd < a_cfg["min_buy_usd"]:
            summary["skipped"]["below min_buy_usd"] += 1
            continue
        if k in recent:
            summary["skipped"]["duplicate within dedupe window"] += 1
            continue
        gk = (b["chain"], b["wallet"])
        if gk not in grades:
            src, fetched = store.fetched(*gk) if not hub.demo else ("demo", 1)
            known = bool(b.get("tracked") or b.get("source", "").startswith("gmgn") or fetched)
            big = (usd or 0) >= d_cfg["big_buy_usd"]
            allow = hub.demo or known or (big and new_grades < d_cfg["max_new_wallet_grades"])
            if not allow:
                summary["skipped"]["unknown wallet, small buy (not graded this run)"] += 1
                continue
            if not hub.demo and not fetched:
                new_grades += 1
            grades[gk] = _grade(hub, cfg, b["chain"], b["wallet"], now_ts)
            summary["graded_wallets"] += 1
        wg = grades[gk][0]
        if GRADE_ORDER.get(wg.grade, 0) < min_rank:
            summary["skipped"][f"wallet grade {wg.grade} below {a_cfg['min_wallet_grade']}"] += 1
            continue
        candidates.append((b, usd))

    seq = ledger.head()[1]
    for b, usd in candidates[: a_cfg["max_alerts_per_run"]]:
        chain, token, wallet = b["chain"], b["token"], b["wallet"]
        wg, positions, trades = grades[(chain, wallet)]
        info = hub.token_info(chain, token) or {}
        if not info.get("pool"):
            summary["skipped"]["no pool/price data"] += 1
            continue
        if fnum(info.get("liq")) < a_cfg["min_liquidity_usd"]:
            summary["skipped"]["liquidity below min"] += 1
            continue
        if a_cfg.get("max_mcap_usd") and fnum(info.get("mcap")) > a_cfg["max_mcap_usd"]:
            summary["skipped"]["market cap above max (not a memecoin play)"] += 1
            continue
        late = late_history(hub, cfg, chain, positions, exclude_token=token)
        candles = hub.ohlcv(chain, info["pool"], b["ts"] - 120, now_ts)
        fw = latecheck.forward_check(candles, b["ts"], b.get("price_usd"), now_ts)
        if fw.get("price_now") is None and info.get("price_usd"):
            fw["price_now"] = info["price_usd"]
        co = []
        for o in by_token[(chain, token)]:
            if o["wallet"] == wallet:
                continue
            og = grades.get((chain, o["wallet"]))
            if og and og[0].grade in ("A", "B", "C"):
                co.append({"wallet": o["wallet"], "grade": og[0].grade, "ts": o["ts"]})
        prior_tok = [t for t in trades if t["token"] == token and t["ts"] < b["ts"]]
        buy_sizes = [fnum(t.get("value")) for t in trades if t["side"] == "buy" and t.get("value_unit") == b.get("value_unit")]
        med_size = median(buy_sizes)
        posts = hub.x_posts(chain, {**info, "address": token})
        if posts is None:
            cinfo = dict(callerg.NOT_CHECKED)
        else:
            cinfo = callerg.grade_chatter(posts, callers, caller_tracked)
            for c in cinfo["callers"]:
                store.add_caller_call(c["handle"], chain, token, info["pool"], c.get("ts") or now_ts, fw.get("price_now"))
        alert = {
            "type": "alert", "id": hashlib.sha256(f"{chain}:{wallet}:{token}:{b['ts']}".encode()).hexdigest()[:16],
            "created_ts": now_ts, "created": utc_iso(now_ts), "demo": bool(hub.demo),
            "chain": chain, "token": token, "symbol": info.get("symbol") or b.get("symbol"), "name": info.get("name"),
            "pool": info["pool"], "dex": info.get("dex"), "url": info.get("url"),
            "wallet": wallet, "wallet_label": b.get("label") or "", "tracked": bool(b.get("tracked")), "tags": b.get("tags") or [],
            "buy_ts": b["ts"], "buy_tx": b.get("tx"), "buy_usd": round(usd, 2) if usd else None,
            "buy_value": b.get("value"), "buy_unit": b.get("value_unit"), "buy_source": b.get("source"),
            "buy_price_usd": fw.get("buy_price") or b.get("price_usd"), "alert_price_usd": fw.get("price_now"),
            "liq": info.get("liq"), "mcap": info.get("mcap"),
            "token_age_s": (now_ts - info["created_ts"]) if info.get("created_ts") else None,
            "wallet_grade": wg.to_dict(), "late": late, "forward": fw, "cobuyers": co,
            "first_buy_of_token": not prior_tok,
            "size_vs_median": round(fnum(b.get("value")) / med_size, 2) if med_size else None,
            "caller": cinfo, "narrative": pick_narrative(ranked, tok_map, chain, token, info),
            "lookback_min": a_cfg["lookback_minutes"], "seq_hint": seq,
        }
        text = story.render(alert)
        if cfg["narration"].get("llm"):
            text = story.narrate_llm(text, alert, cfg["env"])
        alert["text"] = text
        rec = ledger.append(alert)
        seq += 1
        alert["ledger_hash"] = rec["hash"]
        alert["delivered"] = deliver(text + f"\nledger #{rec['seq']} · {rec['hash'][:12]}", cfg["env"],
                                     enabled=deliver_enabled and not hub.demo, log=log)
        summary["alerts"].append(alert)
    summary["skipped"] = dict(summary["skipped"])
    summary["sources"] = hub.status()
    return summary


def score_ledger(hub, store, cfg, now_ts):
    ledger = Ledger(resolve(cfg, "ledger"))
    done = ledger.scores()
    added = []
    horizons = cfg["ledger"]["horizons"]
    for a in ledger.alerts():
        due = [h for h in horizons if h not in done.get(a["id"], {}) and now_ts >= a["created_ts"] + HORIZON_S[h]]
        if not due:
            continue
        end = a["created_ts"] + HORIZON_S[max(due, key=lambda h: HORIZON_S[h])]
        candles = hub.ohlcv(a["chain"], a["pool"], a["buy_ts"] - 120, min(end, now_ts))
        if not candles:
            continue
        p_alert = a.get("alert_price_usd") or latecheck.price_at(candles, a["created_ts"])
        p_buy = a.get("buy_price_usd") or latecheck.price_at(candles, a["buy_ts"])
        p5 = latecheck.price_at(candles, a["buy_ts"] + 300)
        p30 = latecheck.price_at(candles, a["buy_ts"] + 1800)
        for h in sorted(due, key=lambda h: HORIZON_S[h]):
            t = a["created_ts"] + HORIZON_S[h]
            p = latecheck.price_at(candles, t)
            if not p:
                continue
            hi = latecheck.max_high_between(candles, a["created_ts"], t)
            r = lambda x: round(p / x - 1, 4) if x else None
            rec = {"type": "score", "alert_id": a["id"], "horizon": h, "scored_ts": now_ts, "scored": utc_iso(now_ts),
                   "price_usd": p, "ret_from_alert": r(p_alert), "ret_from_wallet_buy": r(p_buy),
                   "ret_if_5m_late": r(p5) if a["buy_ts"] + 300 <= t else None,
                   "ret_if_30m_late": r(p30) if a["buy_ts"] + 1800 <= t else None,
                   "max_ret_from_alert": round(hi / p_alert - 1, 4) if hi and p_alert else None,
                   "demo": a.get("demo", False)}
            added.append(ledger.append(rec))
    # caller calls: 24h peak / price at call
    for handle, chain, token, pool, ts, price in store.unscored_caller_calls(now_ts - 86400):
        c = hub.ohlcv(chain, pool, ts, ts + 86400)
        hi = latecheck.max_high_between(c, ts, ts + 86400)
        if hi and price:
            store.score_caller_call(handle, chain, token, hi / price)
    return added
