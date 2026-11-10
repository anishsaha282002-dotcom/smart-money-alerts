import os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import credit_budget as CB
import helius_stream as HS


def w(addr, score=0, narr=None, stream=True):
    return {"address": addr, "name": addr[:4], "chain": "sol", "score": score,
            "narratives": narr or ["general"], "stream": stream, "enabled": True,
            "source": "https://example.com", "tags": ["smart"]}


class SelectAndDiversify(unittest.TestCase):
    def test_shrink_keeps_top_scores_and_narratives(self):
        wallets = (
            [w(f"Ai{'x'*40}"[:43], score=90-i, narr=["ai_agents"]) for i in range(10)]
            + [w(f"Rw{'y'*40}"[:43], score=80-i, narr=["rwa_tokenization"]) for i in range(10)]
            + [w(f"Wa{'z'*40}"[:43], score=70-i, narr=["war_geopolitics"]) for i in range(10)]
            + [w(f"Mf{'a'*40}"[:43], score=60-i, narr=["major_figures"]) for i in range(10)]
            + [w(f"Gn{'b'*40}"[:43], score=50-i, narr=["general"]) for i in range(40)]
        )
        # make addresses unique and valid-ish length
        for i, x in enumerate(wallets):
            x["address"] = f"Addr{i:04d}" + ("B" * 36)
        picked = CB.select_active_wallets(wallets, shrink=True, shrink_size=30)
        self.assertEqual(len(picked), 30)
        tags = set()
        for x in picked:
            tags.update(x["narratives"])
        for need in ("ai_agents", "rwa_tokenization", "war_geopolitics", "major_figures"):
            self.assertIn(need, tags)
        # top AI wallet (score 90) should be included
        self.assertTrue(any(x["score"] == 90 for x in picked))

    def test_skips_stream_false(self):
        wallets = [w("A" + "B"*43, score=100, stream=False),
                   w("C" + "D"*43, score=10, stream=True)]
        picked = CB.select_active_wallets(wallets, shrink=False)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["score"], 10)


class ObserveActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = HS.SwapStore(self.tmp.name)
        self.cfg = {"daily_cap": 1000, "monthly_cap": 10000, "shrink_size": 50, "shrink_ratio": 0.80}

    def tearDown(self):
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def test_ok_then_shrink_then_pause(self):
        self.assertEqual(CB.observe(self.store, self.cfg)["action"], "ok")
        self.store.bump_credits(800)
        st = CB.observe(self.store, self.cfg)
        self.assertEqual(st["action"], "shrink")
        self.assertEqual(st["day"], 800)
        self.store.bump_credits(200)
        st = CB.observe(self.store, self.cfg)
        self.assertEqual(st["action"], "pause")
        self.assertEqual(st["day"], 1000)

    def test_never_reports_ok_at_or_over_cap(self):
        self.store.bump_credits(1000)
        self.assertEqual(CB.observe(self.store, self.cfg)["action"], "pause")
        self.store.bump_credits(5)
        self.assertEqual(CB.observe(self.store, self.cfg)["action"], "pause")

    def test_credits_include_day(self):
        self.store.bump_credits(3)
        c = self.store.credits()
        self.assertEqual(c["session"], 3)
        self.assertEqual(c["day"], 3)
        self.assertTrue(c["day_date"])


class LoadSmartWalletsReserve(unittest.TestCase):
    def test_shipped_file_has_sources_and_reserve_is_skipped(self):
        import smartmoney as SM
        wallets, notes = SM.load_smart_wallets()
        self.assertTrue(wallets)
        self.assertTrue(all(w.get("address") and w.get("source") for w in wallets))
        self.assertTrue(all(w.get("stream", True) for w in wallets))
        reserved, _ = SM.load_smart_wallets(include_reserve=True)
        self.assertGreaterEqual(len(reserved), len(wallets))


if __name__ == "__main__":
    unittest.main()


class ShardSubs(unittest.TestCase):
    def test_shards_into_100(self):
        import stream_worker as SW
        parts = SW.shard_addresses(list(range(837)), 100)
        self.assertEqual([len(p) for p in parts], [100, 100, 100, 100, 100, 100, 100, 100, 37])
        self.assertEqual(sum(len(p) for p in parts), 837)
