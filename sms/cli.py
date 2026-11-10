"""Command line: `sms demo`, `sms run`, `sms watch`, `sms stream`, `sms grade-wallet`,
`sms score-ledger`, `sms report`, `sms verify`, `sms anchor`, `sms sources`, `sms serve`."""
from __future__ import annotations

import functools
import http.server
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import typer

from . import DISCLAIMER, config, deliver, report
from .grading.wallet import FLAG_TEXT
from .ledger import Ledger, verify_text
from .models import CHAINS, grade_rank, short
from .store import Store
from .story import record_line, sample_line
from .util import duration, pct, share, signed_usd

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Smart Money Stories — free, read-only memecoin alerts in plain English. " + DISCLAIMER)


def _setup(verbose: bool = False):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return config.load()


def _live(settings):
    from .pipeline import Pipeline
    from .sources.hub import LiveHub
    store = Store(settings.data_dir / "state.db")
    ledger = Ledger(settings.data_dir / "ledger.jsonl")
    hub = LiveHub(settings, store)
    return hub, store, ledger, Pipeline(hub, settings, store, ledger, deliver.from_settings(settings))


def _scan(hub, store, ledger, pipe, settings) -> None:
    from .scoring import score_calls, score_ledger
    alerts = pipe.run_once()
    scored = score_ledger(hub, ledger)
    score_calls(hub, store)
    report.export(ledger, store, hub, settings)
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    typer.echo(f"[{stamp} UTC] {len(alerts)} new alert(s), {scored['scores']} price check(s) recorded, "
               f"ledger at {len(ledger)} lines.")


@app.command()
def demo(quiet: bool = typer.Option(False, "--quiet", help="Do not print the sample alert."),
         keep_site: bool = typer.Option(False, "--keep-site", help="Do not overwrite web/data with the demo export.")):
    """Run everything on bundled SYNTHETIC data. No keys, no network."""
    from . import demo as demo_mod
    settings = _setup()
    settings.min_grade = "C"                         # so the small-sample warning shows up too
    settings.chains = CHAINS
    out_dir = settings.data_dir / "demo"
    if out_dir.exists():
        shutil.rmtree(out_dir)                       # the demo is deterministic: start clean every time
    ledger, store = Ledger(out_dir / "ledger.jsonl"), Store(out_dir / "state.db")
    result = demo_mod.run(settings, ledger, store)
    hub = result["hub"]
    alerts = result["alerts"]
    if not quiet:
        rich = [a for a in alerts if a["cluster"] and a["grades"]["caller"]["grade"]] or alerts
        pick = min(rich, key=lambda a: (grade_rank(a["grades"]["wallet"]["grade"]), -a["ts"]))   # best-graded, newest
        typer.echo("\nSAMPLE ALERT (synthetic demo data)\n" + "─" * 64 + "\n" + pick["story"] + "\n" + "─" * 64 + "\n")
    typer.echo(report.text(report.stats(ledger)))
    check = ledger.verify()
    typer.echo(f"\nLedger: {ledger.path}  ({check.lines} lines, hash chain {'OK' if check.ok else 'BROKEN'})")
    if not keep_site:
        out = report.export(ledger, store, hub, settings)
        typer.echo(f"Website data written to {out}/ — preview it with:  sms serve")
    typer.echo("\nThis was SYNTHETIC data: it shows how the tool works, not how any wallet performs.")


@app.command()
def run(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """One live scan: find new buys, alert, score old alerts, refresh the website data."""
    settings = _setup(verbose)
    _scan(*_live(settings), settings)


@app.command()
def watch(interval: int = typer.Option(60, "--interval", "-i", min=20, help="Seconds between scans."),
          verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Scan forever, every --interval seconds. Ctrl-C to stop."""
    settings = _setup(verbose)
    parts = _live(settings)
    typer.echo(f"Watching {', '.join(settings.chains)} every {interval}s. Minimum wallet grade: {settings.min_grade}. Ctrl-C to stop.")
    typer.echo(DISCLAIMER)
    try:
        while True:
            try:
                _scan(*parts, settings)
            except Exception as e:   # noqa: BLE001 - a bad scan must not end the watch
                logging.getLogger("sms").warning("scan failed (%s: %s); trying again next round", type(e).__name__, e)
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("\nStopped.")


@app.command("grade-wallet")
def grade_wallet_cmd(address: str = typer.Argument(..., help="Wallet address (or a demo wallet's name with --demo)."),
                     chain: str = typer.Option("solana", "--chain", "-c", help="solana | bsc | base"),
                     demo: bool = typer.Option(False, "--demo", help="Look the wallet up in the synthetic demo world.")):
    """Grade one wallet and explain the grade."""
    from .pipeline import Pipeline
    settings = _setup()
    if demo:
        from .demo import DemoHub
        hub = DemoHub()
        found = next((w for w in hub.wallets.values() if address in (w["address"], w["label"], w["id"])), None)
        if not found:
            names = ", ".join(w["label"] or w["id"] for w in hub.wallets.values())
            raise typer.BadParameter(f"no such demo wallet. Try one of: {names}")
        address, chain = found["address"], found["chain"]
        store = Store(":memory:")
    else:
        if chain not in CHAINS:
            raise typer.BadParameter(f"chain must be one of {', '.join(CHAINS)}")
        from .sources.hub import LiveHub
        store = Store(settings.data_dir / "state.db")
        hub = LiveHub(settings, store)
    pipe = Pipeline(hub, settings, store, Ledger(settings.data_dir / "ledger.jsonl"))
    g, trades = pipe.grade(chain, address, refresh=True)
    w = g.to_dict()
    typer.echo(f"\nWallet {short(address)} on {chain}" + ("  (synthetic demo wallet)" if demo else ""))
    typer.echo(f"GRADE {g.grade}  ({g.score}/100)\n")
    typer.echo(record_line(w))
    typer.echo(sample_line(w, settings.cap_below))
    if g.n_closed:
        typer.echo(f"Win rate {share(g.win_rate)} raw, {share(g.win_rate_shrunk)} after adjusting for sample size. "
                   f"Return on cost {pct(1 + (g.roi or 0))}, {signed_usd(g.pnl_usd)} realised, typical hold {duration(g.median_hold_s)}.")
    typer.echo("\nScore: " + " + ".join(f"{k.replace('_', ' ')} {v:g}" for k, v in g.parts.items())
               + ("".join(f" − {k} {v}" for k, v in g.penalties.items())) + f" = {g.score}")
    for f in g.flags:
        typer.echo(f"⚠ {FLAG_TEXT.get(f, f)}")
    if g.capped:
        typer.echo("Grade capped at C (too few closed trades, or a serious flag).")
    if not demo and chain == "solana" and not settings.helius_api_key and not settings.gmgn_api_key:
        typer.echo(f"\nNote: no Helius key, so Solana history is the keyless public RPC "
                   f"({len(trades)} trade(s) this run, budgeted). Set HELIUS_API_KEY for the stream store.")
    elif not demo and not (settings.gmgn_api_key or (settings.helius_api_key and chain == "solana")):
        typer.echo(f"\nNote: no history key is set for {chain}, so this is built only from the {len(trades)} trade(s) this "
                   "tool has itself observed. Add HELIUS_API_KEY (Solana) or GMGN_API_KEY (all chains) for 30 days of history.")
    typer.echo("\n" + DISCLAIMER)


@app.command("score-ledger")
def score_ledger_cmd(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Price-check every alert that has reached +15m, +1h, +4h or +24h and append the results."""
    from .scoring import score_calls, score_ledger
    settings = _setup(verbose)
    hub, store, ledger, _ = _live(settings)
    counts = score_ledger(hub, ledger)
    calls = score_calls(hub, store)
    typer.echo(f"Recorded {counts['scores']} price check(s), {counts['copies']} copy check(s), "
               f"{counts['no_data']} with no data; aged {calls} caller mention(s). Ledger at {len(ledger)} lines.")


@app.command("report")
def report_cmd(demo: bool = typer.Option(False, "--demo", help="Report on the demo ledger."),
               no_export: bool = typer.Option(False, "--no-export", help="Print only; leave web/data alone.")):
    """Print the track record by grade, misses included, and refresh the website data."""
    settings = _setup()
    base = settings.data_dir / ("demo" if demo else "")
    ledger = Ledger(base / "ledger.jsonl")
    typer.echo(report.text(report.stats(ledger)))
    if not no_export and not demo:
        from .sources.hub import LiveHub
        store = Store(base / "state.db")
        out = report.export(ledger, store, LiveHub(settings, store), settings)
        typer.echo(f"\nWebsite data refreshed in {out}/")


@app.command()
def verify(path: Path = typer.Argument(None, help="Ledger file. Default: data/ledger.jsonl")):
    """Check the hash chain of a ledger. Exit code 1 if any line was changed."""
    settings = _setup()
    path = path or settings.data_dir / "ledger.jsonl"
    if not path.exists():
        typer.echo(f"No ledger at {path}.")
        raise typer.Exit(1)
    v = verify_text(path.read_text(encoding="utf-8"))
    typer.echo(f"{path}: {v.lines} lines, head {v.head}")
    if v.ok:
        typer.echo("Hash chain OK: every line carries the hash of the one before it.")
        return
    for e in v.errors[:20]:
        typer.echo("✗ " + e)
    raise typer.Exit(1)


@app.command()
def anchor():
    """Write today's head hash into the ledger and stamp it with OpenTimestamps if `ots` is installed."""
    settings = _setup()
    ledger = Ledger(settings.data_dir / "ledger.jsonl")
    if not len(ledger):
        typer.echo("Nothing to anchor: the ledger is empty.")
        raise typer.Exit(1)
    now = int(time.time())
    e = ledger.anchor(now, datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d"), settings.data_dir / "anchors")
    typer.echo(f"Anchored head {e['head']}" + ("  (OpenTimestamps proof written)" if e["ots"]
               else "  (digest saved in data/anchors/; install `opentimestamps-client` to stamp it)"))


@app.command()
def sources():
    """Show which data sources are switched on and which key each one needs."""
    settings = _setup()
    from .sources.hub import LiveHub
    hub = LiveHub(settings, Store(":memory:"))
    for row in hub.status():
        typer.echo(f"{'on ' if row['on'] else 'off'}  {row['source']:<14} {row['needs']}")
    for name, on in (("telegram", settings.telegram_bot_token and settings.telegram_chat_id),
                     ("discord", settings.discord_webhook_url), ("llm rewording", settings.llm_reword and settings.anthropic_api_key)):
        typer.echo(f"{'on ' if on else 'off'}  {name:<14} delivery / optional")


@app.command()
def stream(probe: bool = typer.Option(False, "--probe", help="Check Free-plan subscribe methods, then exit."),
           method: str = typer.Option(None, "--method", help="parsedTransactionSubscribe or logsSubscribe.")):
    """Optional Helius Parsed Streams worker. Needs HELIUS_API_KEY. Never trades.

    Shards 100 addresses per subscription, heartbeats the local store, reconnects,
    and falls back to logsSubscribe. The daily credit cap is 30,000 in America/Chicago
    (STREAM_DAILY_CREDIT_CAP overrides it): shrink to the top 150 at 80%, pause at 100%.
    """
    from .stream_worker import main as stream_main
    argv = ["probe"] if probe else ["run"]
    if method and not probe:
        argv += ["--method", method]
    code = stream_main(argv)
    raise typer.Exit(code or 0)


@app.command()
def serve(port: int = typer.Option(8000, "--port", "-p")):
    """Preview the website locally (it is plain static files)."""
    settings = _setup()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(settings.web_dir))
    typer.echo(f"Serving {settings.web_dir} at http://localhost:{port}  (Ctrl-C to stop)")
    with http.server.ThreadingHTTPServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\nStopped.")


if __name__ == "__main__":
    app()
