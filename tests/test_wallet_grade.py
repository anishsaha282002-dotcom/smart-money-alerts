from conftest import DAY, NOW, history, round_trip

from sms.grading.wallet import close_trades, grade_wallet, shrink_rate
from sms.models import Trade


def test_win_rate_is_shrunk_toward_half_for_small_samples():
    assert shrink_rate(4, 4) == (4 + 5) / 14           # 4 from 4 is treated as 64%, not 100%
    assert shrink_rate(0, 0) == 0.5
    assert abs(shrink_rate(700, 1000) - 0.70) < 0.01   # a big sample is barely moved
    assert shrink_rate(8, 10) < 0.8 < shrink_rate(80, 100) + 0.03


def test_strong_record_grades_a():
    g = grade_wallet(history(20, 6), NOW)
    assert g.grade == "A" and g.n_closed == 26 and g.wins == 20
    assert not g.small_sample and not g.capped and g.flags == []
    assert g.last10_n == 10 and 0 <= g.last10_wins <= 10


def test_losing_record_grades_d():
    g = grade_wallet(history(8, 22, win_roi=0.3), NOW)
    assert g.grade == "D" and g.pnl_usd < 0


def test_tiny_sample_is_capped_at_c_however_good_it_looks():
    g = grade_wallet(history(4, 0, win_roi=2.0), NOW)
    assert g.n_closed == 4 and g.win_rate == 1.0
    assert g.grade == "C" and g.capped and g.small_sample
    assert g.win_rate_shrunk < 0.65


def test_small_sample_flag_without_cap():
    g = grade_wallet(history(6, 1), NOW)
    assert g.small_sample and not g.capped


def test_no_trades_is_a_d_not_a_crash():
    g = grade_wallet([], NOW)
    assert g.grade == "D" and g.n_closed == 0 and g.win_rate is None and g.small_sample


def test_same_trades_same_grade():
    trades = history(12, 7)
    assert grade_wallet(trades, NOW).to_dict() == grade_wallet(list(reversed(trades)), NOW).to_dict()


def test_bot_is_flagged_and_penalised():
    trades = history(40, 20, win_roi=0.03, loss_roi=-0.03, hold=20)
    g = grade_wallet(trades, NOW)
    assert "bot" in g.flags and g.penalties["bot"] > 0 and g.grade == "D"


def test_wash_trading_is_flagged():
    trades = []
    for i in range(12):
        trades += round_trip(token=f"W{i}", buy_ts=NOW - (i + 1) * 9000, hold=120, roi=0.004 if i % 2 else -0.004)
    g = grade_wallet(trades, NOW)
    assert "wash" in g.flags and g.grade in ("C", "D")


def test_sniper_is_flagged_from_token_creation_time():
    trades = []
    for i in range(10):
        ts = NOW - (i + 1) * 30000
        trades += round_trip(token=f"S{i}", buy_ts=ts, hold=600, roi=0.6 if i < 7 else -0.4, created_ts=ts - 1)
    g = grade_wallet(trades, NOW)
    assert "sniper" in g.flags
    clean = grade_wallet([Trade(**{**t.__dict__, "token_created_ts": t.ts - 5000}) for t in trades], NOW)
    assert "sniper" not in clean.flags and clean.score > g.score


def test_fresh_funded_cluster_is_capped_even_with_a_perfect_record():
    trades = history(8, 0, win_roi=1.5)
    g = grade_wallet(trades, NOW, {"first_funded_ts": NOW - DAY, "cluster_size": 3})
    assert "fresh-cluster" in g.flags and g.capped and g.grade in ("C", "D")
    assert grade_wallet(trades, NOW).grade in ("A", "B")


def test_source_tags_become_flags():
    g = grade_wallet(history(15, 5), NOW, {"tags": ["bundler", "rat_trader"]})
    assert {"bundle", "insider"} <= set(g.flags) and g.grade not in ("A", "B")


def test_one_hit_wonder_is_flagged():
    trades = round_trip(token="BIG", roi=40.0, buy_ts=NOW - 3 * DAY)
    for i in range(6):
        trades += round_trip(token=f"L{i}", buy_ts=NOW - (i + 4) * 20000, roi=0.02 if i < 2 else -0.5)
    assert "one-hit" in grade_wallet(trades, NOW).flags


def test_an_old_unsold_bag_counts_as_a_loss():
    bag = [Trade(chain="solana", wallet="W", token="BAG", side="buy", ts=NOW - 12 * DAY, usd=1000, token_amount=1e6, tx="bag")]
    closed = close_trades(bag, NOW)
    assert len(closed) == 1 and closed[0].abandoned and closed[0].pnl == -1000
    fresh = [Trade(chain="solana", wallet="W", token="NEW", side="buy", ts=NOW - 2 * DAY, usd=1000, token_amount=1e6, tx="new")]
    assert close_trades(fresh, NOW) == []          # two days old: still open, not counted either way


def test_sell_without_a_known_buy_is_ignored():
    orphan = [Trade(chain="solana", wallet="W", token="X", side="sell", ts=NOW - DAY, usd=5000, token_amount=1e6, tx="s")]
    assert close_trades(orphan, NOW) == []


def test_only_trades_inside_the_window_count():
    old = round_trip(token="OLD", buy_ts=NOW - 45 * DAY)
    assert close_trades(old, NOW, days=30) == []
    assert len(close_trades(old, NOW, days=60)) == 1


def test_partial_sells_close_at_ninety_percent():
    t = round_trip(token="P")
    half = Trade(**{**t[1].__dict__, "token_amount": 500_000.0, "usd": 900.0, "tx": "half"})
    assert close_trades([t[0], half], half.ts + 600) == []      # half sold a moment ago: still open
    assert len(close_trades(t, NOW)) == 1
    # half sold, the rest untouched for days: closed at what actually came back, not at a guess
    left = close_trades([t[0], half], NOW)
    assert len(left) == 1 and left[0].proceeds == 900.0 and left[0].pnl < 0


def test_identical_buy_sizes_alone_do_not_make_a_bot():
    assert "bot" not in grade_wallet(history(20, 6), NOW).flags      # every buy here is exactly $1,000
