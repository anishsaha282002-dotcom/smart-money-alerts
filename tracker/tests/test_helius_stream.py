#!/usr/bin/env python3
"""Stream parsing, SQLite dedupe, cluster-from-store, webhook-register guard."""
import os, sys, time, json, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import helius_stream as HS
import smartmoney as SM

WALLET = "CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o"
WALLET2 = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"
MEME = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

WALLETS = [
    {"name": "Cented", "address": WALLET, "tags": ["smart", "kol"]},
    {"name": "Decu", "address": WALLET2, "tags": ["smart", "kol"]},
]


def stream_notification(wallet, mint, side, sig, ts=None, amount=1_000_000, decimals=6):
    ts = ts or int(time.time())
    if side == "buy":
        src, dst = "Pool...", wallet
    else:
        src, dst = wallet, "Pool..."
    return {
        "jsonrpc": "2.0",
        "method": "parsedTransactionNotification",
        "params": {"subscription": 1, "result": {"context": {"slot": 1}, "value": {
            "transaction": {
                "signature": sig,
                "slot": 1,
                "blockTime": ts,
                "feePayer": wallet,
                "status": "ok",
                "error": None,
                "summary": {"type": "swap", "parsedData": {
                    "type": "swap", "input_mint": USDC if side == "buy" else mint,
                    "output_mint": mint if side == "buy" else USDC,
                }},
                "tokenTransfers": [{
                    "fromUserAccount": src, "toUserAccount": dst,
                    "rawTokenAmount": amount, "decimals": decimals, "mint": mint,
                }],
            },
            "instructions": [],
        }}},
    }


class ParseStream(unittest.TestCase):
    def test_stream_buy_and_sell(self):
        ts = int(time.time())
        buy = HS.parse_notification(stream_notification(WALLET, MEME, "buy", "sig-buy", ts), WALLETS)
        sell = HS.parse_notification(stream_notification(WALLET, MEME, "sell", "sig-sell", ts), WALLETS)
        self.assertEqual(len(buy), 1)
        self.assertEqual(buy[0]["side"], "buy")
        self.assertEqual(buy[0]["mint"], MEME)
        self.assertEqual(buy[0]["wallet"], WALLET)
        self.assertAlmostEqual(buy[0]["amount"], 1.0)
        self.assertEqual(sell[0]["side"], "sell")

    def test_quote_mint_ignored(self):
        ts = int(time.time())
        rows = HS.parse_notification(stream_notification(WALLET, USDC, "buy", "sig-usdc", ts), WALLETS)
        self.assertEqual(rows, [])

    def test_parsed_events_history_shape(self):
        ts = int(time.time())
        item = {"signature": "hist1", "parsed": {
            "blockTime": ts, "feePayer": WALLET, "transactionStatus": "OK",
            "tokenTransfers": [{
                "fromUserAccount": "Pool...", "toUserAccount": WALLET,
                "rawTokenAmount": {"tokenAmount": "2000000", "decimals": 6}, "mint": MEME,
            }],
        }}
        rows = HS.parse_history_items([item], WALLETS, since_ts=ts - 10, source="poll")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signature"], "hist1")
        self.assertAlmostEqual(rows[0]["amount"], 2.0)

    def test_webhook_body(self):
        ts = int(time.time())
        body = [{"signature": "wh1", "timestamp": ts, "type": "SWAP", "tokenTransfers": [{
            "fromUserAccount": "P", "toUserAccount": WALLET, "tokenAmount": 3, "mint": MEME,
        }]}]
        rows = HS.parse_webhook_body(body, WALLETS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "webhook")


class StoreDedupeAndCluster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = HS.SwapStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_dedupe_same_signature(self):
        ts = int(time.time())
        rows = HS.parse_notification(stream_notification(WALLET, MEME, "buy", "dup-sig", ts), WALLETS)
        self.assertEqual(self.store.insert_many(rows), 1)
        self.assertEqual(self.store.insert_many(rows), 0)
        evs = self.store.events_since(ts - 10, WALLETS)
        self.assertEqual(len(evs), 1)

    def test_cluster_from_stream_rows(self):
        ts = int(time.time())
        r1 = HS.parse_notification(stream_notification(WALLET, MEME, "buy", "a", ts), WALLETS)
        r2 = HS.parse_notification(stream_notification(WALLET2, MEME, "buy", "b", ts), WALLETS)
        self.store.insert_many(r1 + r2)
        evs = self.store.events_since(ts - 10, WALLETS)
        hits = SM.summarize([MEME], evs, [], [], [], wallets=WALLETS, now_ts=ts)
        self.assertTrue(hits[MEME]["sm_confirmed"])
        self.assertIn("2 tracked wallets", hits[MEME]["sm_reason"])
        self.assertTrue(hits[MEME]["kol_buy"])
        self.assertIn("tracked KOL", hits[MEME]["kol_reason"])

    def test_worker_freshness(self):
        self.assertFalse(self.store.worker_fresh(30))
        self.store.heartbeat(method="parsedTransactionSubscribe")
        self.assertTrue(self.store.worker_fresh(30))
        self.store.set_meta("heartbeat_ts", int(time.time()) - 500)
        self.assertFalse(self.store.worker_fresh(30))

    def test_credits_counter(self):
        self.assertEqual(self.store.bump_credits(3), 3)
        self.assertEqual(self.store.credits()["session"], 3)


class WebhookGuard(unittest.TestCase):
    def test_refuses_missing_or_non_https_url(self):
        for url in ("", "http://example.com/hook", "https://localhost/hook", None):
            with self.assertRaises(ValueError):
                HS.register_swap_webhook("dummy-key", url, WALLETS)


class KolAndSellFromTracked(unittest.TestCase):
    def test_one_kol_buy_is_kol_not_cluster(self):
        ts = int(time.time())
        evs = [{"side": "buy", "mint": MEME, "timestamp": ts, "wallet": WALLET,
                "name": "Cented", "tags": ["smart", "kol"], "signature": "a"}]
        hits = SM.summarize([MEME], evs, [], [], [], wallets=WALLETS, now_ts=ts)
        self.assertFalse(hits[MEME]["sm_confirmed"])
        self.assertTrue(hits[MEME]["kol_buy"])
        self.assertEqual(hits[MEME]["confidence"], "KOL buy")

    def test_tracked_sell_is_soft_exit(self):
        ts = int(time.time())
        evs = [{"side": "sell", "mint": MEME, "timestamp": ts, "wallet": WALLET2,
                "name": "Decu", "tags": ["smart", "kol"], "signature": "s"}]
        hits = SM.summarize([MEME], evs, [], [], [], wallets=WALLETS, now_ts=ts)
        self.assertTrue(hits[MEME]["sm_sell"])
        self.assertTrue(hits[MEME]["kol_sell"])
        self.assertIn("tracked wallet sell", hits[MEME]["sell_reason"])


if __name__ == "__main__":
    unittest.main()
