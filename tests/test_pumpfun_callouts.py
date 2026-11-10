"""Pump.fun callout leaderboard: grading merge, weights, flags, boost-only invariant."""
from sma.sources import pumpfun_callouts as pfc
from sma.grading import caller
from sma import story


def _row(username="cupsey", handle="Cupseyy", periods=None, hit_2x=None, call_count=None, flags=None, days=None):
    row = {
        "username": username,
        "x_handle": handle,
        "wallet": "Wallet111",
        "periods": periods or {},
        "call_count": call_count,
        "call_count_period_days": days,
        "flags": flags or [],
    }
    if hit_2x is not None:
        row["recent_call_stats"] = {"hit_2x": hit_2x}
    return row


def _snap(rows):
    return {"callers": rows, "loaded": True}


def test_post_oct10_windows_outweigh_all_time():
    # #1 on all-time only vs #1 on 24h only
    all_only = _row(periods={"all": {"rank": 1, "reward_usdc": 500000}})
    day_only = _row(periods={"1d": {"rank": 1, "reward_usdc": 10000}})
    f_all, _ = pfc.leaderboard_factor(all_only)
    f_day, _ = pfc.leaderboard_factor(day_only)
    assert f_day > f_all
    assert abs(f_all - 0.10) < 1e-9
    assert abs(f_day - 0.35) < 1e-9
    # #1 everywhere is 1.0 before quality tilt
    all_four = _row(periods={p: {"rank": 1, "reward_usdc": 1} for p in pfc.PERIODS})
    f, _ = pfc.leaderboard_factor(all_four)
    assert abs(f - 1.0) < 1e-9


def test_rank_50_is_weak():
    row = _row(periods={"1d": {"rank": 50, "reward_usdc": 1000}})
    f, _ = pfc.leaderboard_factor(row)
    assert 0 < f < 0.02  # 0.35 * (1/50) = 0.007


def test_frequency_penalty_only_when_count_known():
    base = _row(periods={"1d": {"rank": 1, "reward_usdc": 10}})
    f0, _ = pfc.leaderboard_factor(base)
    mild = _row(periods={"1d": {"rank": 1, "reward_usdc": 10}}, call_count=80, days=10)  # 8/day
    very = _row(periods={"1d": {"rank": 1, "reward_usdc": 10}}, call_count=250, days=10)  # 25/day
    f1, m1 = pfc.leaderboard_factor(mild)
    f2, m2 = pfc.leaderboard_factor(very)
    assert f0 == 0.35
    assert abs(f1 - 0.35 * 0.7) < 1e-9
    assert abs(f2 - 0.35 * 0.4) < 1e-9
    assert any("high-frequency" in b for b in m2["bits"])


def test_wash_or_bundle_wallet_zeroes_factor():
    row = _row(periods={"1d": {"rank": 1, "reward_usdc": 10}})
    f, meta = pfc.leaderboard_factor(row, wallet_flags=["wash-like", "bundle/sniper-like"])
    assert f == 0.0 and meta["excluded"]
    assert "wash-like" in meta["exclude_reasons"]


def test_callout_alone_never_creates_buy():
    snap = _snap([_row(periods={"all": {"rank": 1, "reward_usdc": 500000}})])
    is_buy, passes, fails, sig = pfc.callout_alone_never_creates_buy(["Cupseyy"], snap=snap)
    assert is_buy is False
    assert sig is None
    assert fails  # existing fail is untouched
    assert any("boost only" in p.lower() or "leaderboard" in p.lower() for p in passes)


def test_boost_does_not_clear_fails_or_invent_sig_type():
    snap = _snap([_row(periods={"1d": {"rank": 1, "reward_usdc": 10}})])
    passes, fails, sig, factor = pfc.apply_callout_boost(
        [], ["liquidity too low"], None, ["Cupseyy"], snap=snap)
    assert sig is None
    assert fails == ["liquidity too low"]
    assert factor > 0
    assert not pfc.would_buy(fails, sig)


def test_grade_chatter_blends_leaderboard_but_ignores_board_only_names():
    cs = caller.load_callers({"callers": [{"handle": "Cupseyy", "note": ""}]})
    idx = pfc.index_callers(_snap([_row(periods={"1d": {"rank": 1, "reward_usdc": 10000}, "1w": {"rank": 1, "reward_usdc": 20000}})]))
    # A board name that never posted does not appear
    silent = caller.grade_chatter([], cs, leaderboard_idx=idx)
    assert silent["callers"] == []
    # The same caller posting is graded with the blend
    posted = caller.grade_chatter([{"author": "Cupseyy", "ts": 1}], cs, leaderboard_idx=idx)
    assert posted["callers"] and posted["callers"][0]["lb_factor"] > 0
    assert posted["callers"][0]["rate"] > posted["callers"][0]["hit_rate"]
    text = story.render({
        "chain": "solana", "symbol": "TEST", "wallet": "WalletAddress1234567890", "wallet_label": "",
        "seq_hint": 1, "created_ts": 1000, "buy_ts": 580, "buy_usd": 2400,
        "wallet_grade": {"grade": "A", "score": 80, "n_closed": 14, "wins": 11, "last10_wins": 8, "last10_n": 10,
                         "window_days": 30, "win_rate_shrunk": 0.68, "median_return": 0.46, "median_hold_s": 2400,
                         "warnings": [], "flags": [], "data_source": "demo"},
        "late": {"n": 9, "at_buy": 0.46, "late_5m": 0.21, "late_30m": -0.04, "late_5m_n": 9, "too_fast_5m": 0},
        "forward": {"moved_since_buy": 0.12, "minutes_since_buy": 7},
        "caller": posted, "narrative": {}, "liq": 48000, "mcap": 900000,
        "first_buy_of_token": True, "cobuyers": [], "token_age_s": 3600,
    })
    assert "pump.fun callout leaderboard factor" in text
    assert "Not financial advice" in text


def test_real_snapshot_loads_without_inventing():
    snap = pfc.load_snapshot()
    assert snap.get("loaded")
    assert snap["n_callers"] == 128
    # Exact calledcard figure, not a rounded guess
    chair = pfc.lookup(pfc.index_callers(snap), username="chairman")
    assert abs(chair["periods"]["all"]["reward_usdc"] - 509660.248045) < 1e-6
    # Handle comes from pumpbubble, not invented for handle-less names
    src = pfc.lookup(pfc.index_callers(snap), username="bestcook")
    assert src["x_handle"] is None
