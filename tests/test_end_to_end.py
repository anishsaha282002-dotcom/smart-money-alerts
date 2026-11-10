"""Full demo pipeline + a mocked keyless live run."""
import json
import shutil
from pathlib import Path

from sma import cli, http, pipeline, safety
from sma.config import load_config
from sma.hub import LiveHub
from sma.ledger import verify
from sma.store import Store

REPO = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"


def test_demo_end_to_end(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(http, "request_json", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("network in demo")))
    rc = cli.main(["--root", str(tmp_path), "demo"])
    out = capsys.readouterr().out
    assert rc == 0 and not calls
    assert out.count("SMART-MONEY BUY") == 3
    assert "won 8 of last 10 closed trades over 30d" in out
    assert "small sample" in out and "5 min late" in out and "four.meme" in out
    led = tmp_path / "demo-out" / "ledger.jsonl"
    ok, n, head, _ = verify(led)
    assert ok and n == 15                       # 3 alerts + 12 scores
    site = tmp_path / "demo-out" / "site"
    assert (site / "index.html").exists() and "misses included" in (site / "report.md").read_text()
    assert (site / "ledger.jsonl").read_bytes() == led.read_bytes()
    # tamper -> detected
    txt = led.read_text().replace('"buy_usd":2400.0', '"buy_usd":24000.0')
    led.write_text(txt)
    assert cli.main(["--root", str(tmp_path), "verify-ledger", "--ledger", str(led)]) == 1


def _router(fix):
    pools = fix("gt_fourmeme_pools.json")
    trades = fix("gt_trades.json")

    def route(url, **kw):
        safety.check_request(url, kw.get("body"))
        if "geckoterminal" in url and "/trades" in url:
            return trades
        if "geckoterminal" in url and "/ohlcv/" in url:
            return fix("gt_ohlcv.json")
        if "geckoterminal" in url:
            return pools
        if "dexscreener.com/tokens" in url:
            return []
        if "dexscreener" in url:
            return [] if "trending" in url else {}
        if "jup.ag" in url:
            return []
        if "coingecko" in url:
            return {"solana": {"usd": 150}, "binancecoin": {"usd": 600}, "ethereum": {"usd": 3000}}
        if "solana.com" in url:
            return {"result": []}
        raise AssertionError(f"unexpected host {url}")
    return route


def test_keyless_live_run_mocked(tmp_path, monkeypatch, fix):
    for k in ("HELIUS_API_KEY", "GMGN_API_KEY", "X_BEARER_TOKEN", "TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    seen = []
    route = _router(fix)
    monkeypatch.setattr(http, "request_json", lambda url, **kw: (seen.append(url), route(url, **kw))[1])
    shutil.copytree(REPO / "data", tmp_path / "data")
    cfg = load_config("config.yaml", tmp_path)
    store = Store(tmp_path / "s.db")
    s = pipeline.run(LiveHub(cfg, store), store, cfg, 1_900_000_000, deliver_enabled=False, log=lambda *a: None)
    assert isinstance(s["alerts"], list)
    assert not any(h in u for u in seen for h in ("helius", "gmgn", "api.x.com", "telegram", "discord"))
    st = {x["source"]: x["state"] for x in s["sources"]}
    assert st["Helius"].startswith("off") and st["GMGN read-only"].startswith("off") and st["X API"].startswith("off")
