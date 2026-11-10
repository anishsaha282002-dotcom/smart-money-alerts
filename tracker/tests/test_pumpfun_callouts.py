import unittest, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pumpfun_callouts as PFC


class TestPumpfunCallouts(unittest.TestCase):
    def setUp(self):
        self.row = {
            "username": "cupsey", "x_handle": "Cupseyy",
            "periods": {"1d": {"rank": 1, "reward_usdc": 1000},
                        "all": {"rank": 5, "reward_usdc": 500000}},
        }
        self.snap = {"callers": [self.row], "loaded": True}

    def test_post_oct10_weight(self):
        f_all, _ = PFC.leaderboard_factor({"periods": {"all": {"rank": 1, "reward_usdc": 1}}})
        f_day, _ = PFC.leaderboard_factor({"periods": {"1d": {"rank": 1, "reward_usdc": 1}}})
        self.assertGreater(f_day, f_all)

    def test_bundle_flag_excluded(self):
        f, meta = PFC.leaderboard_factor(self.row, wallet_flags=["bundle/sniper-like"])
        self.assertEqual(f, 0.0)
        self.assertTrue(meta["excluded"])

    def test_callout_alone_never_buy(self):
        is_buy, _passes, fails, sig = PFC.callout_alone_never_creates_buy(["Cupseyy"], snap=self.snap)
        self.assertFalse(is_buy)
        self.assertIsNone(sig)
        self.assertTrue(fails)

    def test_boost_does_not_create_signal(self):
        passes, fails, sig, factor = PFC.apply_callout_boost(
            [], ["rug checks failed"], None, ["Cupseyy"], snap=self.snap)
        self.assertIsNone(sig)
        self.assertEqual(fails, ["rug checks failed"])
        self.assertGreater(factor, 0)
        self.assertFalse(PFC.would_buy(fails, sig))

    def test_snapshot_file(self):
        snap = PFC.load_snapshot()
        self.assertTrue(snap.get("loaded"))
        self.assertEqual(snap["n_callers"], 128)


if __name__ == "__main__":
    unittest.main()
