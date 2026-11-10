from conftest import mk_trade
from sma.grading.wallet import build_positions, grade_wallet

NOW = 1_800_000_000


def round_trip(tok, t, cost, proceeds, hold=1800, **kw):
    return [mk_trade(tok, "buy", t, 100, cost, **kw), mk_trade(tok, "sell", t + hold, 100, proceeds, **kw)]


def test_partial_sell_keeps_position_open_until_90pct():
    tr = [mk_trade("T", "buy", 1, 100, 10), mk_trade("T", "sell", 2, 50, 10), mk_trade("T", "sell", 3, 45, 9)]
    ps = build_positions(tr)
    assert len(ps) == 1 and ps[0].closed and abs(ps[0].ret - 0.9) < 1e-9


def test_open_bag_not_counted_and_sell_without_buy_ignored():
    tr = [mk_trade("A", "buy", 1, 100, 10), mk_trade("B", "sell", 2, 100, 50)]
    ps = build_positions(tr)
    assert len(ps) == 1 and not ps[0].closed


def test_unit_mismatch_leg_skipped():
    tr = [mk_trade("A", "buy", 1, 100, 1, unit="sol"), mk_trade("A", "sell", 2, 100, 300, unit="usd")]
    assert not build_positions(tr)[0].closed


def test_record_phrase_and_shrinkage():
    tr = []
    for i in range(10):
        tr += round_trip(f"T{i}", NOW - 86400 * (i + 1), 100, 150 if i < 8 else 50)
    g, _ = grade_wallet("W", "solana", tr, NOW)
    assert g.n_closed == 10 and g.wins == 8
    assert g.record_phrase().startswith("won 8 of last 10 closed trades over 30d")
    assert abs(g.win_rate_shrunk - (8 + 4) / 18) < 1e-9
    assert g.grade in ("A", "B")


def test_low_sample_capped_at_C_with_warning():
    tr = []
    for i in range(4):
        tr += round_trip(f"T{i}", NOW - 86400 * (i + 1), 100, 300)
    g, _ = grade_wallet("W", "solana", tr, NOW)
    assert g.grade == "C" and any("LOW SAMPLE" in w for w in g.warnings)


def test_ungraded_below_min_closed():
    g, _ = grade_wallet("W", "solana", round_trip("T", NOW - 100, 1, 2), NOW)
    assert g.grade == "U"


def test_old_trades_outside_window_excluded():
    tr = round_trip("T", NOW - 40 * 86400, 1, 2) + round_trip("U", NOW - 45 * 86400, 1, 2)
    g, _ = grade_wallet("W", "solana", tr, NOW)
    assert g.n_closed == 0


def test_bot_and_wash_penalties():
    tr = []
    for i in range(30):
        tr += round_trip(f"T{i % 5}", NOW - 86400 + i * 600, 100, 100.5 if i % 2 else 99.7, hold=10)
    g, _ = grade_wallet("W", "solana", tr, NOW)
    assert "bot-like" in g.flags and "wash-like" in g.flags and g.grade == "D"


def test_sniper_flag():
    tr = []
    for i in range(6):
        t = NOW - 86400 * (i + 1)
        tr += round_trip(f"T{i}", t, 100, 200, created=t - 2)
    g, _ = grade_wallet("W", "solana", tr, NOW)
    assert "bundle/sniper-like" in g.flags
