from sma import latecheck


def candles(p):   # p: list of (t, close)
    return [(t, c, c, c, c, 1) for t, c in p]


def test_replay_at_buy_5m_30m():
    cs = candles([(0, 1.0), (300, 1.2), (1800, 1.5), (2400, 2.0)])
    r = latecheck.replay_position(cs, 0, 2400)
    assert abs(r["at_buy"] - 1.0) < 1e-9
    assert abs(r["late_5m"] - (2.0 / 1.2 - 1)) < 1e-9
    assert abs(r["late_30m"] - (2.0 / 1.5 - 1)) < 1e-9


def test_too_fast_to_copy_counts_zero():
    cs = candles([(0, 1.0), (60, 1.5), (300, 1.4), (1800, 1.0)])
    r = latecheck.replay_position(cs, 0, 120)
    assert r["late_5m"] == 0.0 and "late_5m" in r["too_fast"]


def test_own_fill_price_used_at_buy():
    cs = candles([(0, 1.0), (600, 2.0)])
    r = latecheck.replay_position(cs, 0, 600, own_buy_price=1.25)
    assert abs(r["at_buy"] - 0.6) < 1e-9


def test_summary_medians_and_forward():
    reps = [{"at_buy": 0.5, "late_5m": 0.2, "late_30m": -0.1}, {"at_buy": 0.1, "late_5m": -0.1, "late_30m": -0.2},
            {"at_buy": 0.3, "late_5m": 0.1, "late_30m": 0.0}]
    s = latecheck.summarize(reps)
    assert s["n"] == 3 and abs(s["late_5m"] - 0.1) < 1e-9 and abs(s["late_5m_win"] - 2 / 3) < 1e-9
    fw = latecheck.forward_check(candles([(0, 1.0), (420, 1.1)]), 0, None, 430)
    assert abs(fw["moved_since_buy"] - 0.1) < 1e-9 and fw["minutes_since_buy"] == 7.2


def test_gap_too_large_returns_none():
    assert latecheck.price_at(candles([(0, 1.0)]), 7 * 3600) is None
