"""Overnight upgrades: backtest math, base-rate chip, holder structure, Telegram, Pump.fun logs,
bot rule and stream reconnect rules. All offline."""
from __future__ import annotations

import json
import random
import re

from sms import backtest as bt
from sms import stream_worker as sw
from sms.grading import baserate
from sms.sources import pumpfun_logs as pl
from sms.sources import safety, telegram_public as tg
from sms.wallets import bot_reason

from conftest import load

import pytest

T0 = 1_794_000_000


@pytest.fixture(scope="module")
def world_alert(tmp_path_factory):
    from sms import config, demo
    from sms.ledger import Ledger
    from sms.store import Store
    tmp = tmp_path_factory.mktemp("ov")
    s = config.load(environ={"SMS_CONFIG": str(tmp / "none.toml")})
    s.data_dir, s.web_dir, s.min_grade = tmp / "data", tmp / "web", "C"
    out = demo.run(s, Ledger(s.data_dir / "l.jsonl"), Store(":memory:"))
    return out["alerts"][0]


def candles(path):
    """[(minutes after T0, close)] -> 5m candles with high/low = close."""
    return [[T0 + m * 60, p, p, p, p] for m, p in path]


# ------------------------------------------------------------------ backtest

def test_forward_uses_alert_candle_close_and_closed_windows_only():
    c = candles([(0, 1.0), (5, 1.5), (60, 2.5), (360, 0.4), (1440, 0.8)])
    f = bt.forward(c, T0 + 30, now=T0 + 2 * 86400)
    assert f["entry"] == 1.0
    assert f["1h"]["peak_x"] == 2.5 and f["1h"]["x"] == 2.5
    assert f["24h"]["low_x"] == 0.4 and f["24h"]["x"] == 0.8
    young = bt.forward(c, T0 + 30, now=T0 + 7200)
    assert young["1h"] is not None and young["6h"] is None and young["24h"] is None


def test_forward_without_entry_candle_is_unpriced_not_a_loss():
    assert bt.forward(candles([(600, 1.0)]), T0, now=T0 + 86400 * 2) is None


def test_summary_and_order_and_wilson():
    rs = [{"24h": {"x": x, "peak_x": p, "low_x": lo, "quiet": False}} for x, p, lo in
          [(3, 3, 0.9), (0.2, 1.1, 0.1), (1.2, 2.0, 0.8), (0.5, 0.9, 0.4)]]
    s = bt.summarize(rs)
    assert s["n"] == 4 and s["pct_2x"] == 0.5 and s["pct_down50"] == 0.5 and s["median_x"] == 0.85
    c = candles([(0, 1.0), (5, 0.45), (10, 2.2)])
    assert bt.two_x_before_half(c, T0, 3600) is False
    assert bt.two_x_before_half(candles([(0, 1.0), (5, 2.1), (10, 0.3)]), T0, 3600) is True
    lo, hi = bt.wilson(5, 20)
    assert 0.1 < lo < 0.25 < hi < 0.5
    assert bt.max_drawdown(candles([(0, 1.0), (5, 2.0), (10, 0.5)]), T0, 3600) == 0.75


# ------------------------------------------------------------------ base-rate chip

RATES = {"period": "6-10 Nov 2026", "buckets": {
    "cluster>=3/1h": {"24h": {"n": 120, "pct_2x": 0.18, "pct_down50": 0.41, "median_x": 0.7, "ci_2x": [0.12, 0.26]}},
    "kol-bought": {"24h": {"n": 12, "pct_2x": 0.25, "pct_down50": 0.5, "median_x": 0.8}}}}


def test_bucket_matching():
    assert baserate.bucket_for({"sm_cluster": [1, 2, 3]}) == "cluster>=3/1h"
    assert baserate.bucket_for({"sm_cluster": list(range(9))}) == "cluster>=5/1h"
    assert baserate.bucket_for({"sm_cluster": [], "kol": True}) == "kol-bought"
    assert baserate.bucket_for({}) == "any-tracked-buy"
    lead = {"sm_cluster": [{"wallet": "L1"}, {"wallet": "x"}]}
    assert baserate.bucket_for(lead, {"L1"}) == "cluster>=2/1h+callout-leader"
    assert baserate.lookup(lead, RATES, leaders={"L1"}) is None          # no such bucket -> plain cluster>=2 (absent)
    assert baserate.leader_wallets({"callers": [{"wallet": "S1", "wallets": ["0xabc", "S2"]}]}) == {"S1", "S2"}


def test_base_rate_lines_are_history_not_advice():
    br = baserate.lookup({"sm_cluster": [1, 2, 3]}, RATES)
    text = "\n".join(baserate.lines(br))
    assert "Of 120 past alerts" in text and "18% touched 2x" in text and "Not a forecast" in text
    assert not re.search(r"\b(buy now|you should|we recommend|sell now|ape)\b", text, re.I)
    small = baserate.lines(baserate.lookup({"kol": True}, RATES))
    assert small[0].startswith("Not enough history yet: only 12")
    assert baserate.lookup({}, RATES) is None
    assert baserate.lines(None) == ["No backtest on file for this kind of alert yet."]


def test_story_shows_base_rate_and_holders(world_alert):
    from sms import story
    a = dict(world_alert)
    a["base_rate"] = baserate.lookup({"sm_cluster": [1, 2, 3]}, RATES)
    a["safety"] = {"risks": [], "structure": {"top10_pct": 34.0, "insiders_detected": 12, "creator_pct": 3.0,
                                              "holders": 812, "rugged": False}}
    text = story.render(a)
    assert "HOW SIMILAR ALERTS TURNED OUT" in text and "HOLDERS: top 10 own 34%" in text
    assert "Alerts only, not advice" in text


# ------------------------------------------------------------------ holder structure

def test_structure_excludes_pools_and_flags_concentration():
    rep = load("rugcheck_report.json")
    st = safety.parse_structure(rep["with_holders"])
    assert st["top10_pct"] == 36.0                    # the 20% pool holder is not counted
    assert st["insiders_in_top10"] == 2 and st["creator_pct"] == 3.0
    notes = safety.structure_notes(st)
    assert any("top 10 holders" in n for n in notes) and any("insider" in n for n in notes)
    real = safety.parse_structure(rep["insiders"])    # a real report: no holder list, insiders counted
    assert real["top10_pct"] is None and real["insiders_detected"] == 119
    assert safety.parse_structure({"error": "unable to generate report"}) is None


def test_safety_uses_full_report_then_summary(fake_net):
    out = safety.Safety().check("solana", "So1anaMint")
    assert out and out["source"] == "rugcheck"
    paths = [r.url.path for r in fake_net.requests]
    assert paths[0].endswith("/report")


# ------------------------------------------------------------------ telegram

PAGE = """
<div class="tgme_widget_message" data-post="alphachan/101"><div class="tgme_widget_message_text js-message_text" dir="auto">
New one: nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump &amp; 0xAbC0000000000000000000000000000000000001<br/>not advice</div>
<a class="tgme_widget_message_date"><time datetime="2026-11-10T09:00:00+00:00" class="time">09:00</time></a></div>
<div class="tgme_widget_message" data-post="alphachan/102"><div class="tgme_widget_message_text js-message_text" dir="auto">
gm, no address here w1CDt79j5msmGdkPw1EkRNRQRY65xgT8NQ68Mt</div>
<a><time datetime="2026-11-10T09:05:00+00:00"></time></a></div>
"""


def test_telegram_public_page_parses_posts_and_addresses():
    posts = tg.parse_channel(PAGE)
    assert [p["id"] for p in posts] == [101, 102] and posts[0]["url"] == "https://t.me/alphachan/101"
    calls = tg.calls_from_posts(posts)
    assert {(c.chain, c.token) for c in calls} == {("solana", "nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump"),
                                                   ("bsc", "0xabc0000000000000000000000000000000000001")}
    assert all(c.caller == "tg:alphachan" for c in calls)
    assert not tg.is_solana_address("w1CDt79j5msmGdkPw1EkRNRQRY65xgT8NQ68Mt")


def test_telegram_channel_names_are_validated():
    assert tg.TelegramPublic(["@good_name", "../etc", "x"]).channels == ["good_name"]


# ------------------------------------------------------------------ pump.fun logs

def test_pumpfun_trade_event_decodes_from_real_logs():
    value = load("pumpfun_logs.json")
    trades = pl.trades_from_logs(value)
    assert trades and trades[0]["mint"].endswith("pump") and trades[0]["side"] in ("buy", "sell")
    assert trades[0]["wallet"] == "BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"
    assert pl.match(trades, {"someone-else"}) == []
    assert pl.trades_from_logs({**value, "err": {"x": 1}}) == []
    assert pl.subscribe_payload()["method"] == "logsSubscribe"


def test_b58_roundtrip_matches_telegram_validator():
    raw = bytes(range(32))
    assert tg.b58_len(pl.b58encode(raw)) == 32


# ------------------------------------------------------------------ bot rule

def test_bot_rule_catches_named_and_hyperactive_wallets():
    assert bot_reason({"name": "Mayhem Bot", "stats": {"trades": 73664}}) == "named as a bot"
    assert "trades in 30 days" in bot_reason({"name": "x", "stats": {"trades": 20000}})
    assert "transactions a day" in bot_reason({"name": "x", "vetting": {"est_per_day": 2880000}})
    assert bot_reason({"name": "Cupsey", "stats": {"trades": 900}}) is None


def test_book_never_streams_the_bwwk17_bot():
    from sms.wallets import load_records
    rows, _ = load_records()
    bot = next(r for r in rows if r["address"].startswith("BwWK17"))
    assert bot["stream"] is False and "bot" in bot["tags"]


# ------------------------------------------------------------------ stream reconnect

def test_stale_session_waits_60_to_90_seconds():
    rng = random.Random(1)
    for err in ("ConnectionClosedError sent 1011 (internal error) keepalive ping timeout; no close frame received",
                "{'code': -32005, 'message': 'Too many subscriptions'}"):
        assert 60 <= sw.reconnect_delay(err, 1, rng) <= 90
    assert sw.reconnect_delay("TimeoutError", 4) == 4


def test_silence_watchdog_threshold():
    assert sw.silent_for(1000, 1000 + 600) and not sw.silent_for(1000, 1599) and not sw.silent_for(None, 5)


def test_single_instance_lock(tmp_path):
    p = tmp_path / "w.lock"
    first = sw.acquire_lock(str(p))
    assert first is not None
    assert sw.acquire_lock(str(p)) is None
    first.close()
    again = sw.acquire_lock(str(p))
    assert again is not None
    again.close()


# ------------------------------------------------------------------ backtest script

def _script():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "backtest_signals.py"
    spec = importlib.util.spec_from_file_location("backtest_signals", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bundled_buys_count_once_and_cluster_time_is_kth_unit():
    m = _script()
    first = {"a": (100, "s1"), "b": (100, "s2"), "c": (100, "s1"), "d": (400, "s3"), "e": (5000, "s4")}
    us = m.units(first)
    assert len(us) == 3 and us[0]["bundled"] and sorted(us[0]["w"]) == ["a", "b", "c"]
    assert m.cluster_time(us, 2, 1800)[0] == 400
    assert m.cluster_time(us, 3, 1800) is None and m.cluster_time(us, 3, 6 * 3600)[0] == 5000


def test_script_end_to_end_on_a_tiny_db(tmp_path):
    import sqlite3
    m = _script()
    db = sqlite3.connect(tmp_path / "t.db")
    db.execute("create table swaps(sig, wallet, mint, side, tok, sol, usd_q, ts)")
    db.execute("create table ohlcv(mint, ts, o, h, l, c, v)")
    db.execute("create table ohlcv_done(mint, n, t0)")
    for i, w in enumerate(["w1", "w2", "w3"]):
        db.execute("insert into swaps values(?,?,?,?,?,?,?,?)", (f"s{i}", w, "M", "buy", 1, 1, 0, T0 + i * 60))
    for k in range(0, 300):
        p = 1.0 + k * 0.01
        db.execute("insert into ohlcv values(?,?,?,?,?,?,?)", ("M", T0 + k * 300, p, p, p, p, 1))
    db.execute("insert into ohlcv_done values('M', 300, ?)", (T0,))
    db.commit()
    book = {"w1": {"tags": ["kol"], "name": "w1"}, "w2": {"name": "Mayhem Bot"}, "w3": {"name": "w3"}}
    sigs, excluded = m.build_signals(db, book, {"w3"})
    assert "w2" in excluded
    types = {s["type"] for s in sigs}
    assert {"cluster>=2/30m", "kol-bought", "callout-leader-wallet-bought", "any-tracked-buy"} <= types
    b = m.score(db, sigs, T0 + 2 * 86400, {"M"})
    assert b["cluster>=2/30m"]["24h"]["n"] == 1 and b["cluster>=2/30m"]["24h"]["pct_2x"] == 1.0
    assert b["cluster>=2/30m+callout-leader"]["signals"] == 1
