"""Ports from main: wallet split, callout boost, credits, cluster/KOL/SELL, keyless RPC."""
from __future__ import annotations

import json

from sms import credit_budget as cb
from sms.grading.caller import CALLOUT_WEIGHTS, callout_alone_never_creates_buy, callout_factor, grade_callers
from sms.models import Call, Trade
from sms.signals import cluster_wallets, shill_block, soft_sell
from sms.sources.helius_stream import SwapStore
from sms.sources.solana_rpc import parse_rpc_tx
from sms.wallets import load_records, split_book


def test_wallet_snapshot_keeps_the_stream_split():
    rows, _ = load_records()
    streamed = split_book(rows)
    sol_stream = [r for r in rows if r["chain"] == "solana" and r["stream"]]
    sol_reserve = [r for r in rows if r["chain"] == "solana" and not r["stream"]]
    bsc = [r for r in rows if r["chain"] == "bsc"]
    assert len(sol_stream) == 837 and len(sol_reserve) == 325 and len(bsc) == 411
    assert len(streamed.get("solana", [])) == 837
    assert "bsc" not in streamed or streamed["bsc"] == []
    assert all(r["vetting"] for r in rows[:20])
    assert any("kol" in r["tags"] for r in sol_stream)


def test_callout_weights_and_exclusion_and_never_a_buy():
    assert CALLOUT_WEIGHTS == {"1d": 0.35, "1w": 0.30, "1m": 0.25, "all": 0.10}
    row = {"periods": {"1d": {"rank": 1}, "1w": {"rank": 1}, "1m": {"rank": 1}, "all": {"rank": 1}},
           "recent_call_stats": {"hit_2x": 1.0}}
    factor, meta = callout_factor(row)
    assert abs(factor - 1.0) < 1e-9 and not meta["excluded"]
    zero, blocked = callout_factor({**row, "flags": ["wash-like"]})
    assert zero == 0.0 and blocked["excluded"]
    rare = {"periods": {"1d": {"rank": 1}}, "call_count": 100, "call_count_period_days": 1}
    penalised, _ = callout_factor(rare)
    plain, _ = callout_factor({"periods": {"1d": {"rank": 1}}})
    assert penalised < plain
    assert callout_alone_never_creates_buy(["alpha"], {"alpha": row}) is False
    # a rank boosts a caller who already spoke; it does not invent a mention
    empty = grade_callers([], {}, leaderboard={"alpha": row})
    assert empty.grade is None and empty.n_callers == 0
    mentioned = grade_callers(
        [Call(caller="alpha", chain="solana", token="M", ts=1, followers=10_000, text="hi")],
        {"alpha": []}, leaderboard={"alpha": row})
    assert mentioned.n_callers == 1 and abs(mentioned.callers[0]["lb_factor"] - 1.0) < 1e-9
    assert mentioned.callers[0]["grade"] is None          # no aged calls, so still unrated


def test_credit_budget_shrinks_at_80_and_pauses_at_100():
    cfg = cb.load_config(None)
    assert cfg["daily_cap"] == 30_000 and cfg["shrink_size"] == 150 and cfg["shrink_ratio"] == 0.80

    class Store:
        def __init__(self, day):
            self.day = day
        def credits(self):
            return {"day": self.day, "total": self.day, "day_date": "2026-11-10"}

    assert cb.observe(Store(0), cfg)["action"] == "ok"
    assert cb.observe(Store(24_000), cfg)["action"] == "shrink"
    assert cb.observe(Store(30_000), cfg)["action"] == "pause"
    wallets = [{"address": f"A{i}", "chain": "solana", "stream": i % 5 != 0, "score": 1000 - i,
                "narratives": ["general"], "enabled": True} for i in range(400)]
    shrunk = cb.select_active_wallets(wallets, shrink=True, shrink_size=150)
    assert len(shrunk) == 150 and all(w["stream"] for w in shrunk)


def test_cluster_kol_shill_and_soft_sell():
    book = {
        ("solana", "W1"): {"name": "Ann", "tags": ["kol", "smart"], "stream": True},
        ("solana", "W2"): {"name": "Bo", "tags": ["smart"], "stream": True},
        ("solana", "R1"): {"name": "Reserve", "tags": ["kol"], "stream": False},
    }
    now = 1_000_000
    trades = [
        Trade(chain="solana", wallet="W1", token="MINT", side="buy", ts=now - 100, usd=500),
        Trade(chain="solana", wallet="W2", token="MINT", side="buy", ts=now - 50, usd=800),
        Trade(chain="solana", wallet="R1", token="MINT", side="buy", ts=now - 40, usd=900),
    ]
    cluster = cluster_wallets(trades, "solana", "MINT", now, book)
    assert [c["wallet"] for c in cluster] == ["W1", "W2"]
    sell = soft_sell(Trade(chain="solana", wallet="W1", token="MINT", side="sell", ts=now, usd=400), book)
    assert sell and sell["kind"] == "kol"
    assert soft_sell(Trade(chain="solana", wallet="R1", token="MINT", side="sell", ts=now, usd=400), book) is None
    text = "this is a long identical shill post that was pasted by a coordinated group of accounts on purpose today"
    mentions = [type("M", (), {"text": text, "caller": n}) for n in ("a", "b", "c")]
    assert shill_block(mentions, None, [])
    assert shill_block([], 10, [])
    assert shill_block([], 90, ["wash"])
    assert shill_block([], 90, []) is None


def test_stream_store_is_fresh_inside_two_minutes(tmp_path):
    store = SwapStore(str(tmp_path / "swaps.db"))
    assert not store.worker_fresh()
    store.heartbeat(method="parsedTransactionSubscribe")
    assert store.worker_fresh(120)
    added = store.insert_many([
        {"signature": "sig", "wallet": "W", "mint": "M", "side": "buy", "amount": 1, "timestamp": 10, "source": "stream"},
        {"signature": "sig", "wallet": "W", "mint": "M", "side": "buy", "amount": 1, "timestamp": 10, "source": "stream"},
    ])
    assert added == 1                                  # deduped
    assert store.events_since(0, ["W"])[0]["mint"] == "M"


def test_keyless_rpc_parser_ignores_failed_and_unsigned():
    assert parse_rpc_tx({"meta": {"err": "fail"}}, "W") is None
    tx = {
        "blockTime": 50,
        "transaction": {"signatures": ["sig"], "message": {"accountKeys": [
            {"pubkey": "W", "signer": True}, {"pubkey": "OTHER", "signer": False}]}},
        "meta": {
            "err": None, "fee": 5000,
            "preBalances": [2_000_000_000, 0], "postBalances": [1_000_000_000, 0],
            "preTokenBalances": [],
            "postTokenBalances": [{"owner": "W", "mint": "MEME", "uiTokenAmount": {"uiAmount": 10}}],
        },
    }
    trade = parse_rpc_tx(tx, "W")
    assert trade and trade.side == "buy" and trade.token == "MEME" and trade.source == "solana_rpc"
    assert parse_rpc_tx(tx, "OTHER") is None


FORBIDDEN = ("you should buy", "buy now", "sell now", "buy signal", "sell signal")


def test_rendered_alerts_never_recommend_a_trade(tmp_path):
    from sms import config, demo, story
    from sms.ledger import Ledger
    from sms.store import Store
    s = config.load(environ={"SMS_CONFIG": str(tmp_path / "none.toml")})
    s.data_dir, s.web_dir = tmp_path / "data", tmp_path / "web"
    s.min_grade, s.chains = "C", ("solana", "bsc", "base")
    out = demo.run(s, Ledger(s.data_dir / "l.jsonl"), Store(":memory:"))
    blob = "\n".join(a["story"] for a in out["alerts"])
    blob += "\n" + story.render(out["alerts"][0])
    from sms.signals import soft_sell
    from sms.models import Trade
    book = {("solana", "W1"): {"name": "Ann", "tags": ["kol"], "stream": True}}
    info = soft_sell(Trade(chain="solana", wallet="W1", token="M", side="sell", ts=1, usd=1), book)
    blob += "\n" + info["text"]
    low = blob.lower()
    for phrase in FORBIDDEN:
        assert phrase not in low
    assert "Alerts only, not advice. We never tell you to buy or sell; trade decisions are yours." in blob
    assert info["activity"] == "sm_selling"
    # a callout rank, with no wallet trade, is not smart-money activity
    assert callout_alone_never_creates_buy(["alpha"], {"alpha": {"periods": {"1d": {"rank": 1}}}}) is False


def test_leaderboard_file_has_128_callers():
    data = json.loads((__import__("pathlib").Path(__file__).resolve().parents[1]
                        / "data" / "pumpfun_callout_leaderboard.json").read_text(encoding="utf-8"))
    assert data["n_callers"] == 128 and len(data["callers"]) == 128
