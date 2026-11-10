import json, os, time, tempfile
from sma import helius_stream as HS
from sma.sources import solana

W = "CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o"
W2 = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"
MEME = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
WALLETS = [{"name": "Cented", "address": W, "tags": ["smart", "kol"]},
           {"name": "Decu", "address": W2, "tags": ["smart"]}]


def notif(wallet, mint, side, sig, ts):
    src, dst = ("Pool", wallet) if side == "buy" else (wallet, "Pool")
    return {"method": "parsedTransactionNotification", "params": {"result": {"value": {"transaction": {
        "signature": sig, "blockTime": ts, "status": "ok",
        "tokenTransfers": [{"fromUserAccount": src, "toUserAccount": dst,
                            "rawTokenAmount": 1000000, "decimals": 6, "mint": mint}],
    }}}}}


def test_parse_and_dedupe(tmp_path):
    ts = int(time.time())
    db = tmp_path / "s.db"
    store = HS.SwapStore(str(db))
    rows = HS.parse_notification(notif(W, MEME, "buy", "s1", ts), WALLETS)
    assert len(rows) == 1 and rows[0]["side"] == "buy"
    assert store.insert_many(rows) == 1
    assert store.insert_many(rows) == 0
    evs = store.events_since(ts - 5, [W])
    assert len(evs) == 1
    trade = HS.to_sma_trade(evs[0])
    assert trade["token"] == MEME and trade["tx"] == "s1" and trade["wallet"] == W


def test_helius_trades_uses_store_when_fresh(tmp_path, monkeypatch):
    ts = int(time.time())
    db = str(tmp_path / "s.db")
    store = HS.SwapStore(db)
    store.insert_many(HS.parse_notification(notif(W, MEME, "buy", "live1", ts), WALLETS))
    store.heartbeat(method="parsedTransactionSubscribe")
    called = []
    monkeypatch.setattr(HS, "poll_parsed_history", lambda *a, **k: called.append(1) or ([], 10, "should not poll"))
    h = solana.Helius("dummy-key", budget=5, db_path=db)
    got = h.trades(W, ts - 10)
    assert called == []
    assert len(got) == 1 and got[0]["tx"] == "live1" and got[0]["source"] in ("stream", "helius_stream", "webhook", "poll")


def test_helius_trades_polls_when_stale(tmp_path, monkeypatch):
    ts = int(time.time())
    db = str(tmp_path / "s.db")
    HS.SwapStore(db)  # stale, no heartbeat
    item = {"signature": "p1", "parsed": {"blockTime": ts, "transactionStatus": "OK",
            "tokenTransfers": [{"fromUserAccount": "P", "toUserAccount": W,
                                "rawTokenAmount": 5_000_000, "decimals": 6, "mint": MEME}]}}
    monkeypatch.setattr(HS, "poll_parsed_history", lambda *a, **k: ([item], 10, None))
    # point the client's store at our db; poll_parsed_history is on the module the client imported
    import sma.helius_stream as M
    monkeypatch.setattr(M, "poll_parsed_history", lambda *a, **k: ([item], 10, None))
    h = solana.Helius("dummy-key", budget=5, db_path=db)
    got = h.trades(W, ts - 10)
    assert len(got) == 1 and got[0]["tx"] == "p1"
    assert h.calls == 1


def test_register_webhook_requires_https():
    try:
        HS.register_swap_webhook("k", "http://example.com/h", WALLETS)
        assert False, "should have refused"
    except ValueError as e:
        assert "HTTPS" in str(e)
