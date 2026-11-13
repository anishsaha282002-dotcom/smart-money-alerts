"""The public record, read back: how alerts did by grade, misses included, and the site export.

The paper run and the "listed, but not counted as a win" treatment of dead pools follow
cvxv666/fomo-robinhood-radar (MIT), fomo_agent/pipeline/record.py, Copyright (c) 2026
fomo-agent contributors: a fixed stake into every alert, out at a fixed time, nothing left off.
"""
from __future__ import annotations

import json
import shutil
import statistics
from pathlib import Path

from . import DISCLAIMER, __version__
from .ledger import Ledger
from .grading import baserate
from .models import CHAIN_LABEL, GRADES, HORIZONS
from .story import headline
from .store import Store
from .util import pct, signed_usd

STAKE = 100.0
STATE_ORDER = ("new", "rising", "hot", "steady", "fading", "unknown")


def collect(ledger: Ledger) -> list[dict]:
    """Alerts with their later score and copy lines folded in. The ledger itself is not changed."""
    alerts = {e["id"]: {**e, "scores": {}, "copy": None} for e in ledger.entries("alert")}
    for e in ledger.entries("score"):
        if e["alert_id"] in alerts:
            alerts[e["alert_id"]]["scores"][e["h"]] = {k: e.get(k) for k in ("x", "peak_x", "low_x", "status", "held")}
    for e in ledger.entries("copy"):
        if e["alert_id"] in alerts:
            alerts[e["alert_id"]]["copy"] = {k: v for k, v in e.items() if k not in ("seq", "type", "prev", "alert_id")}
    return list(alerts.values())


def _row(alerts: list[dict]) -> dict:
    row: dict = {"n": len(alerts), "h": {}}
    for h in HORIZONS:
        scored = [a["scores"][h] for a in alerts if h in a["scores"]]
        measured = [s for s in scored if s["status"] in ("ok", "quiet")]
        hits = sum(s["status"] == "ok" and s["x"] > 1.0 for s in measured)
        row["h"][h] = {
            "measured": len(measured), "hits": hits,
            "hit_rate": round(hits / len(measured), 3) if measured else None,
            "median_x": round(statistics.median(s["x"] for s in measured), 3) if measured else None,
            "quiet": sum(s["status"] == "quiet" for s in measured),
            "no_data": sum(s["status"] == "no_data" for s in scored),
            "pending": len(alerts) - len(scored),
            "paper_pnl": round(sum(STAKE * (s["x"] - 1) for s in measured), 2),
        }
    day = [a["scores"]["24h"] for a in alerts if a["scores"].get("24h", {}).get("status") in ("ok", "quiet")]
    row["reached_2x"] = round(sum(s["peak_x"] >= 2 for s in day) / len(day), 3) if day else None
    row["down_80"] = round(sum(s["x"] <= 0.2 for s in day) / len(day), 3) if day else None
    return row


def _latest(a: dict) -> tuple[str, dict] | None:
    for h in ("24h", "4h", "1h", "15m"):
        s = a["scores"].get(h)
        if s and s["status"] in ("ok", "quiet"):
            return h, s
    return None


def _brief(a: dict) -> dict:
    latest = _latest(a)
    return {"id": a["id"], "ts": a["ts"], "chain": a["chain"], "symbol": a["token"]["symbol"],
            "wallet_grade": a["grades"]["wallet"]["grade"], "caller_grade": a["grades"]["caller"]["grade"],
            "narrative": a["grades"]["narrative"]["label"], "state": a["grades"]["narrative"]["state"],
            "scores": {h: s["x"] for h, s in a["scores"].items()},
            "status": {h: s["status"] for h, s in a["scores"].items()},
            "at": latest[0] if latest else None, "x": latest[1]["x"] if latest else None}


def stats(ledger: Ledger) -> dict:
    alerts = collect(ledger)
    by = lambda key: {k: _row([a for a in alerts if key(a) == k])        # noqa: E731
                      for k in sorted({key(a) for a in alerts}, key=str)}
    measured = [b for b in (_brief(a) for a in alerts) if b["x"] is not None]
    hour = sorted((a for a in alerts if a["scores"].get("1h", {}).get("status") in ("ok", "quiet")), key=lambda a: a["ts"])
    total, curve = 0.0, []
    for a in hour:
        total += STAKE * (a["scores"]["1h"]["x"] - 1)
        curve.append({"ts": a["ts"], "id": a["id"], "total": round(total, 2)})
    copies = [a["copy"] for a in alerts if a["copy"] and a["copy"].get("status") == "ok"]
    verdicts: dict[str, int] = {}
    for c in copies:
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1

    return {
        "alerts": len(alerts), "lines": len(ledger), "head": ledger.head, "stake": STAKE,
        "first_ts": min((a["ts"] for a in alerts), default=None), "last_ts": max((a["ts"] for a in alerts), default=None),
        "overall": _row(alerts),
        "by_wallet_grade": {g: _row([a for a in alerts if a["grades"]["wallet"]["grade"] == g]) for g in GRADES},
        "by_caller_grade": by(lambda a: a["grades"]["caller"]["grade"] or "none"),
        "by_narrative_state": by(lambda a: a["grades"]["narrative"]["state"]),
        "by_chain": by(lambda a: a["chain"]),
        "by_signal": by(lambda a: baserate.bucket_for(a)),
        "misses": sorted((b for b in measured if b["x"] < 1), key=lambda b: b["x"])[:15],
        "best": sorted((b for b in measured if b["x"] >= 1), key=lambda b: -b["x"])[:8],
        "n_misses": sum(b["x"] < 1 for b in measured), "n_measured": len(measured),
        "copy_verdicts": verdicts, "curve": curve,
    }


def leaderboard(store: Store, limit: int = 60) -> list[dict]:
    rows = []
    for key in store.keys("grade:"):
        v = store.get(key)
        copy = store.get(f"copy:{v['chain']}:{v['wallet']}") or None
        rows.append({"chain": v["chain"], "wallet": v["wallet"], "label": v.get("label") or "",
                     "twitter": v.get("twitter") or "", **v["grade"], "copy": copy})
    rows.sort(key=lambda r: (-r["score"], -r["n_closed"]))
    return rows[:limit]


def _paper(settings):
    from . import paper
    from .ledger import Ledger as _L
    path = settings.data_dir / "paper.jsonl"
    return paper.summary(_L(path), paper.PaperRules()) if path.exists() else None


def site(ledger: Ledger, store: Store, hub, settings) -> dict:
    alerts = sorted(collect(ledger), key=lambda a: -a["ts"])
    board = store.get("narratives") or {}
    narratives = sorted((n for n in board.values() if n["key"] != "other"),
                        key=lambda n: (STATE_ORDER.index(n["state"]), -(n["share_now"] or 0)))
    return {
        "meta": {"generated_ts": hub.now(), "demo": bool(getattr(hub, "demo", False)), "version": __version__,
                 "disclaimer": DISCLAIMER, "chains": [CHAIN_LABEL.get(c, c) for c in settings.chains],
                 "min_grade": settings.min_grade, "sources": hub.status(),
                 "worker": hub.worker_health() if hasattr(hub, "worker_health") else None, "head": ledger.head, "lines": len(ledger)},
        "ticker": [{"id": a["id"], "ts": a["ts"], "text": headline(a), "grade": a["grades"]["wallet"]["grade"]}
                   for a in alerts[:14]],
        "alerts": [{k: v for k, v in a.items() if k not in ("seq", "type", "prev")}
                   for a in (alerts + list(ledger.entries("sm_selling")))][:80],
        "narratives": narratives,
        "wallets": leaderboard(store),
        "stats": stats(ledger),
        "paper": _paper(settings),
        "baserates": baserate.load(),
    }


def export(ledger: Ledger, store: Store, hub, settings) -> Path:
    """Write web/data/site.json and a copy of the ledger for the in-browser verifier."""
    out = Path(settings.web_dir) / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "site.json").write_text(json.dumps(site(ledger, store, hub, settings), ensure_ascii=False,
                                              separators=(",", ":")), encoding="utf-8")
    if ledger.path.exists():
        shutil.copyfile(ledger.path, out / "ledger.jsonl")
    else:
        (out / "ledger.jsonl").write_text("", encoding="utf-8")
    return out


def text(s: dict) -> str:
    """The same numbers as the website, for the terminal."""
    lines = [f"PUBLIC RECORD — {s['alerts']} alerts, {s['lines']} ledger lines",
             f"head hash {s['head']}", ""]
    if not s["alerts"]:
        return "\n".join(lines + ["No alerts on the record yet."])
    head = f"{'wallet grade':<13}{'alerts':>7}" + "".join(f"{h + ' hit':>10}{h + ' med':>9}" for h in HORIZONS) + f"{'2x peak':>9}{'-80%':>7}"
    lines += [head, "-" * len(head)]
    rows = [(g, s["by_wallet_grade"][g]) for g in GRADES] + [("ALL", s["overall"])]
    for name, r in rows:
        if not r["n"]:
            continue
        cells = ""
        for h in HORIZONS:
            c = r["h"][h]
            hit = f"{c['hits']}/{c['measured']}" if c["measured"] else "—"
            cells += f"{hit:>10}{pct(c['median_x']):>9}"
        two = f"{r['reached_2x'] * 100:.0f}%" if r["reached_2x"] is not None else "—"
        dead = f"{r['down_80'] * 100:.0f}%" if r["down_80"] is not None else "—"
        lines.append(f"{name:<13}{r['n']:>7}{cells}{two:>9}{dead:>7}")
    o = s["overall"]["h"]["1h"]
    lines += ["",
              "hit = price above the alert-time price at that checkpoint; med = median move.",
              f"Paper run: ${STAKE:.0f} into every alert, out an hour later: {signed_usd(o['paper_pnl'])} over {o['measured']} alerts.",
              f"Misses (below the alert price at the latest checkpoint): {s['n_misses']} of {s['n_measured']} measured."]
    if s["misses"]:
        lines.append("Worst: " + ", ".join(f"${m['symbol']} {pct(m['x'])} ({m['wallet_grade']})" for m in s["misses"][:6]))
    if s["copy_verdicts"]:
        lines.append("Copy check: " + ", ".join(f"{k} ×{v}" for k, v in sorted(s["copy_verdicts"].items())))
    lines += ["", DISCLAIMER]
    return "\n".join(lines)
