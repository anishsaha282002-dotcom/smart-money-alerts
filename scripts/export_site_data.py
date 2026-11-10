#!/usr/bin/env python3
"""Export the public alert ledger and caller/wallet lists into web/data/ for the static site.

Reads only public project files (ledger JSONL, data/callers.json, data/wallets.json).
Never reads .env, credentials, or private keys. Demo/synthetic ledger rows are kept
out of alerts.json unless --include-demo is passed. Use --write-sample to build the
clearly labeled example file loaded by the page only with ?sample=1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
HORIZONS = ("15m", "1h", "4h", "24h")
SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret_key|private_key|privatekey|mnemonic|seed_phrase|"
    r"password|authorization|bearer_token|bot_token|webhook_url|"
    r"helius_api|llm_api|gmgn_api|x_bearer)",
    re.I,
)


def utc_iso(ts=None) -> str:
    if ts is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_root(start: Path | None = None) -> Path:
    if start is not None:
        return Path(start).resolve()
    here = Path(__file__).resolve().parent
    # scripts/ lives at the repo root
    if (here.parent / "config.yaml").exists() or (here.parent / "pyproject.toml").exists():
        return here.parent
    return Path.cwd()


def sanitize(obj):
    """Drop secret-looking keys. Public token mints and wallet addresses are kept."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if not SECRET_KEY_RE.search(str(k))}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def verify_ledger(path: Path):
    """Return (ok, n_lines, head_hash, records, problems). Does not require the sma package."""
    if not path.exists():
        return True, 0, GENESIS, [], []
    raw = path.read_text(encoding="utf-8")
    problems = []
    if raw and not raw.endswith("\n"):
        problems.append("file does not end with a newline (truncated write?)")
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    prev = GENESIS
    records = []
    for i, ln in enumerate(lines):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            problems.append(f"line {i + 1}: not valid JSON")
            prev = line_hash(ln)
            continue
        if obj.get("prev") != prev:
            problems.append(f"line {i + 1}: prev hash mismatch")
        if obj.get("seq") is not None and obj.get("seq") != i:
            problems.append(f"line {i + 1}: seq {obj.get('seq')} != {i}")
        records.append(obj)
        prev = line_hash(ln)
    return (not problems), len(lines), prev, records, problems


def _pct(v):
    if v is None:
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _copy_verdict(late):
    m5 = (late or {}).get("late_5m")
    n = (late or {}).get("late_5m_n") or 0
    if n < 3 or m5 is None:
        return "not enough replayable history to say"
    if m5 >= 0.10:
        return "historically still worth it 5 min late"
    if m5 > 0:
        return "thin edge if you are 5 min late"
    return "historically NOT worth copying 5 min late"


def _why(alert: dict) -> list[str]:
    out = []
    if alert.get("first_buy_of_token"):
        out.append("first time this wallet has bought this token")
    svm = alert.get("size_vs_median")
    if svm and svm >= 2:
        out.append(f"{float(svm):.1f}x its usual buy size")
    co = alert.get("cobuyers") or []
    if co:
        grades = ", ".join(sorted({c.get("grade") or "?" for c in co}))
        look = alert.get("lookback_min", 60)
        out.append(f"{len(co)} other graded wallet(s) ({grades}) bought it in the last {look}m")
    age = alert.get("token_age_s")
    if age is not None and age < 6 * 3600:
        hours = age / 3600
        out.append(f"token is only {hours:.1f}h old" if hours >= 1 else f"token is only {int(age // 60)}m old")
    n = alert.get("narrative") or {}
    if n.get("status") in ("NEW", "RISING", "HOT") and n.get("narrative"):
        out.append(f"its narrative '{n['narrative']}' is {n['status']}")
    if alert.get("tracked"):
        out.append("wallet is on your watch list")
    for t in (alert.get("tags") or [])[:2]:
        out.append(f"tag: {t}")
    if not out:
        wg = alert.get("wallet_grade") or {}
        grade = wg.get("grade") or "?"
        out.append(f"a grade-{grade} wallet opened a new position")
    return out


def _decision(alert: dict) -> str:
    raw = (alert.get("decision") or alert.get("side") or "").strip().upper()
    if raw in ("BUY", "SELL"):
        return raw
    text = alert.get("text") or ""
    head = text.split("\n", 1)[0].upper()
    if re.search(r"\bSELL\b", head):
        return "SELL"
    return "BUY"


def _is_kol(alert: dict) -> bool:
    tags = [str(t).lower() for t in (alert.get("tags") or [])]
    if any("kol" in t for t in tags):
        return True
    src = str(alert.get("buy_source") or "").lower()
    if "kol" in src:
        return True
    return False


def _explorers(chain: str, token: str, url: str | None) -> dict:
    chain = (chain or "").lower()
    dex_chain = {"solana": "solana", "bsc": "bsc", "base": "base"}.get(chain, chain or "solana")
    out = {
        "dexscreener": url if (url and "dexscreener.com" in url) else (f"https://dexscreener.com/{dex_chain}/{token}" if token else None),
    }
    if chain == "bsc" and token:
        out["scan"] = f"https://bscscan.com/token/{token}"
        out["scan_label"] = "BscScan"
    elif chain == "base" and token:
        out["scan"] = f"https://basescan.org/token/{token}"
        out["scan_label"] = "BaseScan"
    elif token:
        out["scan"] = f"https://solscan.io/token/{token}"
        out["scan_label"] = "Solscan"
    return out


def card_from_alert(alert: dict, scores: dict) -> dict:
    wg = alert.get("wallet_grade") or {}
    late = alert.get("late") or {}
    caller = alert.get("caller") or {}
    cobuyers = [
        {"address": c.get("wallet") or c.get("address"), "grade": c.get("grade"), "ts": c.get("ts")}
        for c in (alert.get("cobuyers") or [])
    ]
    caller_rows = []
    for c in (caller.get("callers") or [])[:6]:
        caller_rows.append({
            "handle": c.get("handle"),
            "grade": c.get("grade"),
            "rate": _pct(c.get("rate")),
            "n_eff": c.get("n_eff"),
        })
    scored = scores.get(alert.get("id") or "", {})
    outcomes = {}
    for h in HORIZONS:
        row = scored.get(h) or {}
        if not row:
            continue
        outcomes[h] = {
            "ret_from_alert": _pct(row.get("ret_from_alert")),
            "ret_from_wallet_buy": _pct(row.get("ret_from_wallet_buy")),
            "ret_if_5m_late": _pct(row.get("ret_if_5m_late")),
            "ret_if_30m_late": _pct(row.get("ret_if_30m_late")),
            "max_ret_from_alert": _pct(row.get("max_ret_from_alert")),
            "scored": row.get("scored"),
        }
    narr = alert.get("narrative") or {}
    narrative = None
    if narr.get("narrative"):
        narrative = {
            "narrative": narr.get("narrative"),
            "status": narr.get("status"),
            "score": narr.get("score"),
            "n_tokens": narr.get("n_tokens"),
            "vol_h1": narr.get("vol_h1"),
        }
    late_out = None
    if late:
        late_out = {
            "n": late.get("n") or late.get("late_5m_n") or 0,
            "late_5m": _pct(late.get("late_5m")),
            "late_30m": _pct(late.get("late_30m")),
            "at_buy": _pct(late.get("at_buy")),
            "too_fast_5m": late.get("too_fast_5m") or 0,
            "verdict": _copy_verdict(late),
        }
    chain = alert.get("chain") or "solana"
    token = alert.get("token") or ""
    sm_confirmed = len(cobuyers) >= 1
    card = {
        "id": alert.get("id"),
        "seq": alert.get("seq"),
        "decision": _decision(alert),
        "created": alert.get("created") or (utc_iso(alert["created_ts"]) if alert.get("created_ts") else None),
        "created_ts": alert.get("created_ts"),
        "chain": chain,
        "symbol": alert.get("symbol") or "?",
        "name": alert.get("name") or alert.get("symbol") or "Unknown",
        "token": token,
        "dex": alert.get("dex"),
        "url": alert.get("url"),
        "explorers": _explorers(chain, token, alert.get("url")),
        "text": alert.get("text") or "",
        "why": _why(alert),
        "wallet": {
            "address": alert.get("wallet") or wg.get("wallet"),
            "label": alert.get("wallet_label") or "",
            "grade": wg.get("grade"),
            "score": wg.get("score"),
            "n_closed": wg.get("n_closed"),
            "win_rate_shrunk": _pct(wg.get("win_rate_shrunk")),
            "tracked": bool(alert.get("tracked")),
        },
        "cobuyers": cobuyers,
        "caller": {
            "grade": caller.get("grade"),
            "checked": bool(caller.get("checked")),
            "reason": caller.get("reason"),
            "posts": caller.get("posts"),
            "callers": caller_rows,
        },
        "sm_confirmed": sm_confirmed,
        "kol_buy": _is_kol(alert),
        "late": late_out,
        "outcomes": outcomes or None,
        "narrative": narrative,
        "buy_usd": alert.get("buy_usd"),
        "liq": alert.get("liq"),
        "mcap": alert.get("mcap"),
        "demo": bool(alert.get("demo")),
    }
    return sanitize(card)


def records_to_alerts(records, include_demo=False):
    scores = {}
    alerts = []
    for r in records:
        if r.get("type") == "score" and r.get("alert_id"):
            scores.setdefault(r["alert_id"], {})[r.get("horizon") or ""] = r
        elif r.get("type") == "alert":
            alerts.append(r)
    cards = []
    skipped_demo = 0
    for a in alerts:
        if a.get("demo") and not include_demo:
            skipped_demo += 1
            continue
        cards.append(card_from_alert(a, scores))
    # newest first
    cards.sort(key=lambda c: (c.get("created_ts") or 0, c.get("seq") or 0), reverse=True)
    return cards, skipped_demo


def summarize_callers(path: Path) -> dict:
    if not path.exists():
        return {"source": str(path.name), "exists": False, "callers": [], "flagged": [], "catalysts": []}
    raw = sanitize(json.loads(path.read_text(encoding="utf-8")))
    callers = []
    for row in raw.get("callers") or []:
        callers.append({
            "handle": row.get("handle"),
            "tier": row.get("tier"),
            "lang": row.get("lang"),
            "note": row.get("note") or "",
            "group": "caller",
        })
    flagged = []
    for row in raw.get("flagged") or []:
        flagged.append({
            "handle": row.get("handle"),
            "tier": "flagged",
            "lang": row.get("lang"),
            "note": row.get("why") or row.get("note") or "",
            "group": "flagged",
        })
    catalysts = []
    for row in raw.get("catalysts") or []:
        catalysts.append({
            "handle": row.get("handle"),
            "tier": "catalyst",
            "lang": row.get("lang"),
            "note": row.get("note") or "",
            "group": "catalyst",
        })
    return {
        "source": path.name,
        "exists": True,
        "generated": utc_iso(),
        "counts": {"callers": len(callers), "flagged": len(flagged), "catalysts": len(catalysts)},
        "callers": callers,
        "flagged": flagged,
        "catalysts": catalysts,
    }


def summarize_wallets(path: Path) -> dict:
    if not path.exists():
        return {"source": str(path.name), "exists": False, "wallets": []}
    raw = sanitize(json.loads(path.read_text(encoding="utf-8")))
    wallets = []
    for row in raw.get("wallets") or []:
        wallets.append({
            "name": row.get("name") or "",
            "chain": row.get("chain") or "solana",
            "address": row.get("address"),
            "tags": row.get("tags") or [],
            "source": row.get("source") or "",
        })
    return {
        "source": path.name,
        "exists": True,
        "generated": utc_iso(),
        "counts": {"wallets": len(wallets)},
        "wallets": wallets,
    }


def counts_for(cards):
    out = {"alerts": len(cards), "buy": 0, "sell": 0, "solana": 0, "bsc": 0, "base": 0, "sm_confirmed": 0, "kol_buy": 0}
    for c in cards:
        d = (c.get("decision") or "").lower()
        if d == "buy":
            out["buy"] += 1
        elif d == "sell":
            out["sell"] += 1
        ch = (c.get("chain") or "").lower()
        if ch in out:
            out[ch] += 1
        if c.get("sm_confirmed"):
            out["sm_confirmed"] += 1
        if c.get("kol_buy"):
            out["kol_buy"] += 1
    return out


def export(*, root: Path, ledger_path: Path, out_dir: Path, include_demo=False, example=False, source_label=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    ok, n_lines, head, records, problems = verify_ledger(ledger_path)
    cards, skipped_demo = records_to_alerts(records, include_demo=include_demo or example)
    payload = {
        "generated": utc_iso(),
        "example": bool(example),
        "source": source_label or (str(ledger_path.relative_to(root)) if _safe_rel(ledger_path, root) else str(ledger_path.name)),
        "ledger": {
            "exists": ledger_path.exists(),
            "path": ledger_path.name,
            "lines": n_lines,
            "alerts": sum(1 for r in records if r.get("type") == "alert"),
            "head": head,
            "ok": ok,
            "problems": problems[:8],
            "skipped_demo": skipped_demo,
        },
        "counts": counts_for(cards),
        "alerts": cards,
        "disclaimer": "Signals only. Not financial advice. This tool never trades.",
    }
    if example:
        payload["example_note"] = "EXAMPLE DATA from bundled demo fixtures — not live market calls."
    alerts_name = "alerts.sample.json" if example else "alerts.json"
    (out_dir / alerts_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, alerts_name


def _safe_rel(path: Path, root: Path):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export public ledger/callers/wallets to web/data/ for the static calls page.")
    ap.add_argument("--root", type=Path, default=None, help="repo root (default: parent of this script)")
    ap.add_argument("--ledger", type=Path, default=None, help="ledger JSONL (default: <root>/public/ledger.jsonl)")
    ap.add_argument("--out", type=Path, default=None, help="output directory (default: <root>/web/data)")
    ap.add_argument("--callers", type=Path, default=None)
    ap.add_argument("--wallets", type=Path, default=None)
    ap.add_argument("--include-demo", action="store_true", help="include ledger rows marked demo=true in alerts.json (off by default)")
    ap.add_argument("--write-sample", action="store_true", help="write alerts.sample.json from --ledger (for ?sample=1), leave alerts.json alone unless also exporting")
    ap.add_argument("--sample-only", action="store_true", help="only write the sample file, do not refresh alerts.json")
    args = ap.parse_args(argv)

    root = repo_root(args.root)
    out_dir = (args.out if args.out and args.out.is_absolute() else root / (args.out or Path("web/data"))).resolve()
    if args.out and not args.out.is_absolute():
        out_dir = (root / args.out).resolve()
    ledger = args.ledger or (root / "public" / "ledger.jsonl")
    if args.ledger and not Path(args.ledger).is_absolute():
        cand = Path(args.ledger)
        ledger = cand if cand.exists() else (root / cand)
    callers_path = args.callers or (root / "data" / "callers.json")
    wallets_path = args.wallets or (root / "data" / "wallets.json")

    written = []
    if not args.sample_only:
        payload, name = export(root=root, ledger_path=Path(ledger), out_dir=out_dir, include_demo=args.include_demo, example=False)
        written.append(name)
        callers = summarize_callers(Path(callers_path))
        wallets = summarize_wallets(Path(wallets_path))
        (out_dir / "callers.json").write_text(json.dumps(callers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out_dir / "wallets.json").write_text(json.dumps(wallets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.extend(["callers.json", "wallets.json"])
        print(f"wrote {out_dir / name}: {payload['counts']['alerts']} call(s) "
              f"(ledger exists={payload['ledger']['exists']}, lines={payload['ledger']['lines']}, "
              f"skipped_demo={payload['ledger']['skipped_demo']}, chain={'OK' if payload['ledger']['ok'] else 'BROKEN'})")
        print(f"wrote {out_dir / 'callers.json'}: {callers.get('counts', {})}")
        print(f"wrote {out_dir / 'wallets.json'}: {wallets.get('counts', {})}")

    if args.write_sample or args.sample_only:
        if not Path(ledger).exists():
            sys.exit(f"cannot write sample: ledger not found at {ledger}")
        payload, name = export(root=root, ledger_path=Path(ledger), out_dir=out_dir, include_demo=True, example=True)
        written.append(name)
        print(f"wrote {out_dir / name}: {payload['counts']['alerts']} EXAMPLE call(s) (labeled, not live)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
