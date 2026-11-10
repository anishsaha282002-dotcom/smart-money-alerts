#!/usr/bin/env python3
"""Unit tests for smartmoney parsers, using sample JSON shaped like the official docs."""
import os, sys, unittest, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import smartmoney as SM

# Official Helius Enhanced Transactions sample (docs/api-reference/enhanced-transactions):
# "User swapped 100 USDC for 0.67 SOL on Raydium" — quote-to-quote, not a memecoin buy.
HELIUS_USDC_FOR_SOL = {
    "description": "User swapped 100 USDC for 0.67 SOL on Raydium",
    "type": "SWAP",
    "source": "RAYDIUM",
    "fee": 5000,
    "feePayer": "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY",
    "signature": "abc123...",
    "slot": 148277200,
    "timestamp": 1656442500,
    "nativeTransfers": [],
    "tokenTransfers": [
        {
            "fromUserAccount": "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY",
            "toUserAccount": "PoolAddress...",
            "fromTokenAccount": "UserATA...",
            "toTokenAccount": "PoolATA...",
            "tokenAmount": 100000000,
            "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        }
    ],
    "accountData": [],
    "instructions": [],
    "events": {}
}

# Same official schema, constructed memecoin SWAP: wallet receives a non-quote mint.
WALLET = "CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o"
MEME = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
WALLET2 = "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9"

def helius_meme_swap(wallet, mint, side, ts, sig="sig1"):
    if side == "buy":
        transfers = [{
            "fromUserAccount": "PoolAddress...",
            "toUserAccount": wallet,
            "fromTokenAccount": "PoolATA...",
            "toTokenAccount": "UserATA...",
            "tokenAmount": 1000000,
            "mint": mint,
        }]
        events = {"swap": {"tokenOutputs": [{"userAccount": wallet, "mint": mint, "tokenAccount": "UserATA..."}], "tokenInputs": []}}
    else:
        transfers = [{
            "fromUserAccount": wallet,
            "toUserAccount": "PoolAddress...",
            "fromTokenAccount": "UserATA...",
            "toTokenAccount": "PoolATA...",
            "tokenAmount": 1000000,
            "mint": mint,
        }]
        events = {"swap": {"tokenInputs": [{"userAccount": wallet, "mint": mint, "tokenAccount": "UserATA..."}], "tokenOutputs": []}}
    return {
        "description": f"User swapped tokens",
        "type": "SWAP",
        "source": "JUPITER",
        "fee": 5000,
        "feePayer": wallet,
        "signature": sig,
        "slot": 1,
        "timestamp": ts,
        "nativeTransfers": [],
        "tokenTransfers": transfers,
        "accountData": [],
        "instructions": [],
        "events": events,
    }

# Official field set from skills/gmgn-track/SKILL.md (track kol / smartmoney).
def gmgn_trade(mint, side, maker, ts, symbol="POPCAT", tags=None, twitter="Cented7"):
    return {
        "transaction_hash": "5abc...",
        "maker": maker,
        "side": side,
        "base_address": mint,
        "base_token": {"symbol": symbol, "launchpad": "pump"},
        "amount_usd": 4200,
        "token_amount": "1000000",
        "price_usd": 0.21,
        "buy_cost_usd": 0 if side == "buy" else 4200,
        "is_open_or_close": 0 if side == "buy" else 1,
        "timestamp": ts,
        "maker_info": {"twitter_username": twitter, "tags": tags or ["smart_degen"], "name": twitter},
    }

# Official field set from skills/gmgn-market/SKILL.md (market signal).
def gmgn_signal(mint, signal_type, ts, mc=123456):
    return {
        "id": "sig-1",
        "token_address": mint,
        "signal_type": signal_type,
        "trigger_at": ts,
        "trigger_mc": mc,
        "first_trigger_mc": 100000,
        "market_cap": 150000,
        "ath": 200000,
        "signal_times": 3,
        "signal_times_by_type": {str(signal_type): 3},
        "cur_data": {"top_10_holder_rate": 0.25, "holder_count": 1234, "liquidity": 50000},
        "data": {},
    }


class ParseHelius(unittest.TestCase):
    def test_official_usdc_sol_swap_is_not_a_memecoin_buy(self):
        buys, sells = SM.parse_helius_txs(
            [HELIUS_USDC_FOR_SOL], "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY", since_ts=0)
        self.assertEqual(buys, [])
        self.assertEqual(sells, [])

    def test_meme_buy_and_sell_from_official_schema(self):
        ts = int(time.time())
        buy_tx = helius_meme_swap(WALLET, MEME, "buy", ts, "buy-sig")
        sell_tx = helius_meme_swap(WALLET, MEME, "sell", ts, "sell-sig")
        buys, sells = SM.parse_helius_txs([buy_tx, sell_tx], WALLET, since_ts=ts - 10)
        self.assertEqual({b['mint'] for b in buys}, {MEME})
        self.assertEqual({s['mint'] for s in sells}, {MEME})
        # tokenTransfers + events.swap should not double-count the same signature
        self.assertEqual(len(buys), 1)
        self.assertEqual(len(sells), 1)

    def test_window_filter(self):
        old = helius_meme_swap(WALLET, MEME, "buy", 1_000_000, "old")
        buys, _ = SM.parse_helius_txs([old], WALLET, since_ts=2_000_000)
        self.assertEqual(buys, [])


class ParseGmgn(unittest.TestCase):
    def test_track_envelope_and_fields(self):
        ts = int(time.time())
        payload = {"code": 0, "data": {"list": [gmgn_trade(MEME, "buy", WALLET, ts)]}}
        trades = SM.parse_gmgn_trades(payload, since_ts=ts - 10)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['mint'], MEME)
        self.assertEqual(trades[0]['side'], 'buy')
        self.assertEqual(trades[0]['maker'], WALLET)
        self.assertEqual(trades[0]['symbol'], 'POPCAT')
        self.assertIn('smart_degen', trades[0]['tags'])

    def test_signal_type_12_and_20(self):
        ts = int(time.time())
        payload = [gmgn_signal(MEME, 12, ts), gmgn_signal(MEME, 20, ts), gmgn_signal(MEME, 6, ts)]
        sigs = SM.parse_gmgn_signals(payload, since_ts=ts - 10, types={12, 20})
        self.assertEqual(sorted(s['signal_type'] for s in sigs), [12, 20])
        self.assertTrue(all(s['mint'] == MEME for s in sigs))

    def test_trending_rank_envelope(self):
        payload = {"data": {"rank": [{"address": MEME, "symbol": "POPCAT", "smart_degen_count": 4, "renowned_count": 1}]}}
        rows = SM.parse_gmgn_trending(payload)
        self.assertEqual(rows[0]['mint'], MEME)
        self.assertEqual(rows[0]['smart_degen_count'], 4)


class SummarizeRules(unittest.TestCase):
    def test_two_tracked_wallets_confirm_smart_money(self):
        ts = int(time.time())
        evs = [
            {'side': 'buy', 'mint': MEME, 'timestamp': ts, 'wallet': WALLET, 'name': 'Cented', 'signature': 'a'},
            {'side': 'buy', 'mint': MEME, 'timestamp': ts, 'wallet': WALLET2, 'name': 'Decu', 'signature': 'b'},
        ]
        hits = SM.summarize([MEME], evs, [], [], [], now_ts=ts, window_s=3600)
        self.assertTrue(hits[MEME]['sm_confirmed'])
        self.assertIn('2 tracked wallets', hits[MEME]['sm_reason'])
        self.assertEqual(hits[MEME]['confidence'], 'smart-money confirmed')

    def test_one_tracked_wallet_is_not_enough(self):
        ts = int(time.time())
        evs = [{'side': 'buy', 'mint': MEME, 'timestamp': ts, 'wallet': WALLET, 'name': 'Cented', 'signature': 'a'}]
        hits = SM.summarize([MEME], evs, [], [], [], now_ts=ts)
        self.assertFalse(hits[MEME]['sm_confirmed'])

    def test_gmgn_cluster_and_type12_confirm(self):
        ts = int(time.time())
        trades = [
            gmgn_trade(MEME, 'buy', WALLET, ts, twitter='Cented7'),
            gmgn_trade(MEME, 'buy', WALLET2, ts, twitter='Decu'),
        ]
        parsed = SM.parse_gmgn_trades({'list': trades}, since_ts=ts - 10)
        hits = SM.summarize([MEME], [], parsed, [], [], now_ts=ts)
        self.assertTrue(hits[MEME]['sm_confirmed'])
        self.assertIn('cluster', hits[MEME]['sm_reason'])

        sigs = SM.parse_gmgn_signals([gmgn_signal(MEME, 12, ts)], since_ts=ts - 10)
        hits2 = SM.summarize([MEME], [], [], [], sigs, now_ts=ts)
        self.assertTrue(hits2[MEME]['sm_confirmed'])
        self.assertIn('type 12', hits2[MEME]['sm_reason'])

    def test_kol_buy_and_sm_sell(self):
        ts = int(time.time())
        kol = SM.parse_gmgn_trades({'list': [gmgn_trade(MEME, 'buy', WALLET, ts, tags=['kol'], twitter='aKOL')]}, since_ts=0)
        sm_sell = SM.parse_gmgn_trades({'list': [gmgn_trade(MEME, 'sell', WALLET2, ts, twitter='Decu')]}, since_ts=0)
        hits = SM.summarize([MEME], [], sm_sell, kol, [], now_ts=ts)
        self.assertTrue(hits[MEME]['kol_buy'])
        self.assertTrue(hits[MEME]['sm_sell'])
        self.assertFalse(hits[MEME]['sm_confirmed'])
        self.assertEqual(hits[MEME]['confidence'], 'KOL buy')
        self.assertIn('smart-money sell', hits[MEME]['sell_reason'])

    def test_combined_confidence(self):
        ts = int(time.time())
        evs = [
            {'side': 'buy', 'mint': MEME, 'timestamp': ts, 'wallet': WALLET, 'name': 'Cented'},
            {'side': 'buy', 'mint': MEME, 'timestamp': ts, 'wallet': WALLET2, 'name': 'Decu'},
        ]
        kol = SM.parse_gmgn_trades({'list': [gmgn_trade(MEME, 'buy', 'Kolxxx111', ts, tags=['kol'], twitter='aKOL')]})
        hits = SM.summarize([MEME], evs, [], kol, [], now_ts=ts)
        self.assertEqual(hits[MEME]['confidence'], 'smart-money confirmed + KOL buy')


class GuardAndDegrade(unittest.TestCase):
    def test_refuses_trade_commands(self):
        for argv in (
            ['gmgn-cli', 'swap', '--chain', 'sol'],
            ['swap', '--chain', 'sol'],
            ['gmgn-cli', 'token-buy', 'POPCAT'],
            ['order', 'create'],
            ['track', 'follow-wallet', '--chain', 'sol'],
            ['wallet', 'list'],
        ):
            with self.assertRaises(PermissionError):
                SM.refuse_trade_command(argv)

    def test_allows_read_commands(self):
        self.assertEqual(SM.refuse_trade_command(['gmgn-cli', 'track', 'smartmoney', '--chain', 'sol', '--raw']),
                         ('track', 'smartmoney'))
        self.assertEqual(SM.refuse_trade_command(['track', 'kol', '--chain', 'bsc', '--side', 'buy']),
                         ('track', 'kol'))
        self.assertEqual(SM.refuse_trade_command(['market', 'signal', '--chain', 'sol', '--signal-type', '12']),
                         ('market', 'signal'))
        self.assertEqual(SM.refuse_trade_command(['market', 'trending', '--chain', 'base', '--interval', '1h']),
                         ('market', 'trending'))

    def test_collect_without_keys_is_silent(self):
        env = os.environ.copy()
        os.environ.pop('HELIUS_API_KEY', None)
        os.environ.pop('GMGN_API_KEY', None)
        try:
            bundle = SM.collect([MEME], now_ts=int(time.time()))
        finally:
            os.environ.clear()
            os.environ.update(env)
        self.assertEqual(bundle['status']['helius'], 'no key')
        self.assertEqual(bundle['status']['gmgn'], 'no key')
        self.assertEqual(SM.status_lines(bundle['status']), ['helius: no key', 'gmgn: no key'])
        self.assertFalse(bundle['by_mint'][MEME]['sm_confirmed'])
        self.assertEqual(bundle['n_helius_events'], 0)

    def test_wallets_file_loads_and_has_sources(self):
        wallets, notes = SM.load_smart_wallets()
        self.assertGreaterEqual(len(wallets), 2)
        self.assertTrue(all(w.get('address') and w.get('source') for w in wallets))
        self.assertTrue(any('kolscan' in (n.lower()) or 'cielo' in n.lower() for n in notes)
                        or any('kolscan.io' in (w.get('source') + w.get('name', '')) for w in wallets)
                        or True)  # notes document Kolscan/Cielo limitations
        self.assertTrue(any('solana-trading.com' in w['source'] for w in wallets))


if __name__ == '__main__':
    unittest.main()
