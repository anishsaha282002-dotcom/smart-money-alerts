"""`sma` command line. Read/report commands only - there is no buy/sell/swap command."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import __version__, pipeline, report, safety
from .config import load_config, resolve
from .hub import DemoHub, LiveHub
from .ledger import Ledger, verify
from .store import Store
from .util import pct, utc_iso, human_dur

PKG_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo"


def _fixtures_dir(cfg):
    for p in (Path(cfg["root"]) / "fixtures" / "demo", PKG_FIXTURES):
        if (p / "meta.json").exists():
            return p
    sys.exit("demo fixtures not found (expected fixtures/demo/meta.json)")


def _setup(args, demo=False):
    cfg = load_config(args.config, args.root)
    if demo:
        out = Path(cfg["root"]) / "demo-out"
        cfg["paths"]["ledger"] = str(out / "ledger.jsonl")
        cfg["paths"]["site_dir"] = str(out / "site")
        cfg["paths"]["callers"] = str(_fixtures_dir(cfg) / "callers.json")
        store = Store(out / "demo.db")
        hub = DemoHub(cfg, store, _fixtures_dir(cfg))
        now = int(getattr(args, "now", None) or hub.meta["now_ts"])
    else:
        store = Store(Path(resolve(cfg, "data_dir")) / "state.db")
        hub = LiveHub(cfg, store)
        now = int(getattr(args, "now", None) or time.time())
    return cfg, store, hub, now


def _print_summary(s):
    print(f"\n== run {s['now']} UTC: {len(s['alerts'])} alert(s), {s.get('buys_seen', 0)} buys seen, "
          f"{s['graded_wallets']} wallets graded")
    for k, v in sorted(s["skipped"].items(), key=lambda kv: -kv[1]):
        print(f"   skipped {v:>4} × {k}")
    if s.get("narratives_top"):
        print("   narratives: " + "; ".join(f"{n} {st} {sc:.1f}" for n, st, sc in s["narratives_top"][:6]))
    for src in s.get("sources", []):
        extra = f" calls={src['calls']}" if "calls" in src else ""
        err = f" errors={src['errors']}" if src.get("errors") else ""
        print(f"   source {src['source']}: {src['state']}{extra}{err}")


def cmd_run(args):
    cfg, store, hub, now = _setup(args, args.demo)
    s = pipeline.run(hub, store, cfg, now, deliver_enabled=not args.no_deliver)
    _print_summary(s)
    return s


def cmd_watch(args):
    i = 0
    while True:
        args.now = None
        cmd_run(args)
        cfg, store, hub, now = _setup(args, args.demo)
        added = pipeline.score_ledger(hub, store, cfg, now)
        print(f"   scored {len(added)} ledger horizon(s)")
        i += 1
        if args.iterations and i >= args.iterations:
            break
        time.sleep(max(60, args.interval * 60))


def cmd_score(args):
    cfg, store, hub, now = _setup(args, args.demo)
    added = pipeline.score_ledger(hub, store, cfg, now)
    print(f"scored {len(added)} horizon(s) at {utc_iso(now)} UTC")
    for r in added:
        print(f"  alert {r['alert_id']} +{r['horizon']}: from alert {pct(r['ret_from_alert'])}, "
              f"from wallet buy {pct(r['ret_from_wallet_buy'])}, 5m late {pct(r['ret_if_5m_late'])}, "
              f"30m late {pct(r['ret_if_30m_late'])}")
    return added


def cmd_report(args):
    cfg, store, hub, now = _setup(args, args.demo)
    out = args.out or cfg["paths"]["site_dir"]
    out = Path(out) if Path(out).is_absolute() else Path(cfg["root"]) / out
    lp = resolve(cfg, "ledger")
    if lp.exists() and lp.parent.resolve() != out.resolve():
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy(lp, out / "ledger.jsonl")      # the site always ships the exact ledger bytes
    path, ok = report.build(cfg, out, now)
    print(f"report: {path} (ledger chain {'OK' if ok else 'BROKEN'})")
    return path


def cmd_grade(args):
    cfg, store, hub, now = _setup(args, args.demo)
    wg, positions, trades = pipeline._grade(hub, cfg, args.chain, args.address, now)
    d = wg.to_dict()
    print(f"wallet {args.address} on {args.chain}: grade {wg.grade} ({wg.score:.0f}/100) - {wg.record_phrase()}")
    print(f"  data: {wg.data_source}, {wg.trades_seen} trades, {wg.n_closed} closed / {wg.n_open} open positions in window")
    if wg.win_rate_shrunk is not None:
        print(f"  win rate raw {wg.win_rate_raw * 100:.0f}% -> sample-adjusted {wg.win_rate_shrunk * 100:.0f}%; "
              f"median return {pct(wg.median_return)}; profit factor {wg.profit_factor}; "
              f"median hold {human_dur(wg.median_hold_s) if wg.median_hold_s else 'n/a'}")
    for w in wg.warnings + [f"flag: {f}" for f in wg.flags]:
        print(f"  ! {w}")
    if args.late:
        late = pipeline.late_history(hub, cfg, args.chain, positions)
        d["late"] = late
        print(f"  copy check over {late['n']} replayed trades: at its price {pct(late.get('at_buy'))}, "
              f"5m late {pct(late.get('late_5m'))}, 30m late {pct(late.get('late_30m'))}")
    if args.json:
        print(json.dumps(d, indent=1, default=str))
    return d


def cmd_verify(args):
    cfg = load_config(args.config, args.root)
    lp = Path(args.ledger) if args.ledger else resolve(cfg, "ledger")
    ok, n, head, problems = verify(lp)
    print(f"{lp}: {n} lines, head {head} -> {'OK' if ok else 'BROKEN'}")
    for p in problems[:20]:
        print("  " + p)
    return 0 if ok else 1


def cmd_anchor(args):
    cfg = load_config(args.config, args.root)
    lp = Path(args.ledger) if args.ledger else resolve(cfg, "ledger")
    ok, n, head, _ = verify(lp)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    d = lp.parent / "anchors"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.txt"
    f.write_text(f"ledger={lp.name}\nlines={n}\nhead_sha256={head}\nchain_ok={ok}\nutc={utc_iso(time.time())}\n")
    print(f"wrote {f}. To anchor in Bitcoin (free, optional): pip install opentimestamps-client && ots stamp {f}")


def cmd_demo(args):
    root = Path(load_config(args.config, args.root)["root"])
    out = root / "demo-out"
    if out.exists():
        shutil.rmtree(out)
    args.demo, args.no_deliver = True, True
    print("== demo: bundled fixtures, no keys, no network ==\n")
    args.now = None
    s = cmd_run(args)
    cfg, store, hub, now = _setup(args, True)
    args.now, args.out = now + 25 * 3600, None
    print("\n== scoring the ledger 25h later (fixture prices) ==")
    cmd_score(args)
    path = cmd_report(args)
    rc = cmd_verify(argparse.Namespace(config=args.config, root=args.root, ledger=str(out / "ledger.jsonl")))
    print(f"\nopen {path}")
    return rc


def cmd_sources(args):
    cfg = load_config(args.config, args.root)
    env = cfg["env"]
    rows = [("GeckoTerminal", "keyless", "pools, trades with wallet addresses, OHLCV, four.meme"),
            ("DexScreener", "keyless", "token -> best pool, liquidity, metas"),
            ("Jupiter", "keyless", "Solana trending (narratives)"), ("CoinGecko", "keyless", "SOL/BNB/ETH USD price"),
            ("Solana public RPC", "keyless", "wallet history for Solana (slow, budgeted)"),
            ("Helius", "set" if env["HELIUS_API_KEY"] else "missing HELIUS_API_KEY", "stream store or Parsed Events poll (not 100-credit history)"),
            ("GMGN read-only", "set" if env["GMGN_API_KEY"] else "missing GMGN_API_KEY", "smart-money/KOL feed, SOL/BSC/Base wallet activity"),
            ("X API", "set" if env["X_BEARER_TOKEN"] else "missing X_BEARER_TOKEN", "caller chatter"),
            ("Telegram", "set" if env["TELEGRAM_BOT_TOKEN"] and env["TELEGRAM_CHAT_ID"] else "off", "delivery"),
            ("Discord", "set" if env["DISCORD_WEBHOOK_URL"] else "off", "delivery"),
            ("LLM narration", "set" if env["LLM_API_KEY"] and cfg["narration"].get("llm") else "off", "optional rewrite")]
    for name, state, what in rows:
        print(f"  {name:<20} {state:<28} {what}")


COMMANDS = {"run": cmd_run, "watch": cmd_watch, "score-ledger": cmd_score, "report": cmd_report,
            "grade-wallet": cmd_grade, "verify-ledger": cmd_verify, "anchor": cmd_anchor, "demo": cmd_demo,
            "sources": cmd_sources}


def build_parser():
    ap = argparse.ArgumentParser(prog="sma", description="Explained, graded, auditable smart-money alerts. Read-only; never trades.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--root", default=None, help="project dir (default: cwd)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("run", help="one pass: find buys, grade, alert, append to ledger")
    p.add_argument("--demo", action="store_true"); p.add_argument("--no-deliver", action="store_true"); p.add_argument("--now", type=int)
    p = sp.add_parser("watch", help="run + score-ledger every N minutes")
    p.add_argument("--interval", type=float, default=15); p.add_argument("--iterations", type=int, default=0)
    p.add_argument("--demo", action="store_true"); p.add_argument("--no-deliver", action="store_true")
    p = sp.add_parser("score-ledger", help="append +15m/+1h/+4h/+24h outcomes for due alerts")
    p.add_argument("--demo", action="store_true"); p.add_argument("--now", type=int)
    p = sp.add_parser("report", help="build static HTML/Markdown report from the ledger")
    p.add_argument("--out"); p.add_argument("--demo", action="store_true"); p.add_argument("--now", type=int)
    p = sp.add_parser("grade-wallet", help="grade one wallet and explain it")
    p.add_argument("address"); p.add_argument("--chain", default="solana", choices=["solana", "bsc", "base"])
    p.add_argument("--late", action="store_true", help="also replay its trades for the copy check")
    p.add_argument("--json", action="store_true"); p.add_argument("--demo", action="store_true"); p.add_argument("--now", type=int)
    p = sp.add_parser("verify-ledger", help="check the hash chain"); p.add_argument("--ledger")
    p = sp.add_parser("anchor", help="write today's head hash for OpenTimestamps"); p.add_argument("--ledger")
    p = sp.add_parser("demo", help="zero-key end-to-end demo (run, score, report, verify)")
    sp.add_parser("sources", help="show which sources/keys are active")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    safety.check_command(args.cmd)
    r = COMMANDS[args.cmd](args)
    if isinstance(r, int):
        return r
    return 0


if __name__ == "__main__":
    sys.exit(main())
