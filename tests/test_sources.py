from sma.sources import geckoterminal, solana
from sma.sources.gmgn import GMGN
from sma import http


def test_gt_trades_parse(fix, monkeypatch):
    monkeypatch.setattr(http, "request_json", lambda url, **kw: fix("gt_trades.json"))
    rows = geckoterminal.GeckoTerminal().pool_trades("solana", "POOL")
    assert rows and all(r["wallet"] and r["side"] in ("buy", "sell") and r["value_unit"] == "usd" for r in rows)
    b = next(r for r in rows if r["side"] == "buy")
    assert b["token"] != "So11111111111111111111111111111111111111112"


def test_gt_ohlcv_sorted(fix, monkeypatch):
    monkeypatch.setattr(http, "request_json", lambda url, **kw: fix("gt_ohlcv.json"))
    cs = geckoterminal.GeckoTerminal().ohlcv("solana", "POOL", 0, 600)
    assert [c[0] for c in cs] == sorted(c[0] for c in cs) and len(cs[0]) == 6


def test_gt_fourmeme_pools(fix, monkeypatch):
    seen = []
    monkeypatch.setattr(http, "request_json", lambda url, **kw: (seen.append(url), fix("gt_fourmeme_pools.json"))[1])
    rows = geckoterminal.GeckoTerminal().fourmeme_pools()
    assert "dexes/four-meme/pools" in seen[0]
    assert rows[0]["chain"] == "bsc" and rows[0]["dex"] == "four-meme" and rows[0]["address"].startswith("0x")


W = "Wa11et1111111111111111111111111111111111111"
MEME = "Meme1111111111111111111111111111111111111pump"


def rpc_tx(sol_pre, sol_post, tok_pre, tok_post, fee=5000):
    return {"blockTime": 100, "meta": {"err": None, "fee": fee, "preBalances": [sol_pre], "postBalances": [sol_post],
                                       "preTokenBalances": [{"accountIndex": 1, "mint": MEME, "owner": W, "uiTokenAmount": {"uiAmountString": str(tok_pre)}}],
                                       "postTokenBalances": [{"accountIndex": 1, "mint": MEME, "owner": W, "uiTokenAmount": {"uiAmountString": str(tok_post)}}]},
            "transaction": {"signatures": ["sig1"], "message": {"accountKeys": [{"pubkey": W}]}}}


def test_solana_rpc_buy_and_sell():
    b = solana.parse_rpc_tx(rpc_tx(2_000_000_000, 1_000_000_000 - 5000, 0, 1000), W)
    assert b["side"] == "buy" and abs(b["value"] - 1.0) < 1e-9 and b["value_unit"] == "sol" and b["token_amount"] == 1000
    s = solana.parse_rpc_tx(rpc_tx(1_000_000_000, 2_500_000_000 - 5000, 1000, 0), W)
    assert s["side"] == "sell" and abs(s["value"] - 1.5) < 1e-9


def test_solana_failed_tx_ignored():
    t = rpc_tx(2, 1, 0, 1)
    t["meta"]["err"] = {"x": 1}
    assert solana.parse_rpc_tx(t, W) is None


def test_helius_parse():
    tx = {"signature": "s", "timestamp": 5, "feePayer": W, "fee": 5000,
          "accountData": [{"account": W, "nativeBalanceChange": -500_005_000, "tokenBalanceChanges": []},
                          {"account": "ata", "nativeBalanceChange": 0, "tokenBalanceChanges": [
                              {"userAccount": W, "mint": MEME, "rawTokenAmount": {"tokenAmount": "123000000", "decimals": 6}}]}]}
    t = solana.parse_helius_tx(tx, W)
    assert t["side"] == "buy" and abs(t["value"] - 0.5) < 1e-9 and abs(t["token_amount"] - 123) < 1e-9


def test_gmgn_activity_parse(monkeypatch):
    payload = {"code": 0, "data": {"activities": [
        {"event_type": "buy", "token": {"address": "0xABC", "symbol": "X"}, "timestamp": 200, "cost_usd": "50", "token_amount": "10", "tx_hash": "h1"},
        {"event_type": "transfer_out", "token": {"address": "0xABC"}, "timestamp": 199},
        {"event_type": "sell", "token": {"address": "0xABC"}, "timestamp": 150, "cost_usd": "80", "token_amount": "10", "tx_hash": "h2"}],
        "next": ""}}
    seen = []
    monkeypatch.setattr(http, "request_json", lambda url, **kw: (seen.append((url, kw.get("headers"))), payload)[1])
    rows = GMGN("KEY").wallet_trades("bsc", "0xw", since_ts=0)
    assert [r["side"] for r in rows] == ["buy", "sell"] and rows[0]["token"] == "0xabc"
    assert "/v1/user/wallet_activity" in seen[0][0] and seen[0][1]["X-APIKEY"] == "KEY"
