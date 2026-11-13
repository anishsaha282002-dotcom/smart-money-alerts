"""Paper trading: imaginary money, fixed rules, losses kept."""
from sms.ledger import Ledger
from sms.paper import PaperRules, eligible, simulate_exit, state, step, summary

R = PaperRules()
T0 = 1_000_000


def alert(**over):
    a = {"id": "a-00001", "ts": T0, "activity": "sm_buying", "chain": "solana", "entry_price": 1.0,
         "token": {"address": "COIN", "symbol": "COIN", "pool": "P"}, "mcap_usd": 400_000, "liquidity_usd": 60_000,
         "cluster": [{"wallet": "W2"}, {"wallet": "W3"}], "holding": {"held": 1.0},
         "safety": {"risks": []}, "grades": {"wallet": {"grade": "A"}, "narrative": {"state": "rising"}}}
    a.update(over)
    return a


def test_entry_rules():
    assert eligible(alert(), R) == (True, "ok")
    assert not eligible(alert(cluster=[]), R)[0]
    assert "already sold" in eligible(alert(holding={"held": 0.2}), R)[1]
    assert "narrative" in eligible(alert(grades={"wallet": {"grade": "A"}, "narrative": {"state": "fading"}}), R)[1]
    assert "grade" in eligible(alert(grades={"wallet": {"grade": "C"}, "narrative": {"state": "new"}}), R)[1]
    assert "safety" in eligible(alert(safety={"risks": ["flagged as a honeypot"]}), R)[1]
    assert "market cap" in eligible(alert(mcap_usd=50_000_000), R)[1]
    assert not eligible(alert(demo=True), R)[0]


def c(i, hi, lo, cl):
    return [T0 + 60 * i, cl, hi, lo, cl, 1.0]


def test_stop_loss_costs_about_a_third():
    ex = simulate_exit([c(1, 1.0, 0.6, 0.6)], 1.0, T0, R, T0 + 120)
    assert ex["why"] == "stop loss" and 0.6 < ex["x"] < 0.65


def test_half_at_2x_then_trailing_stop():
    candles = [c(1, 2.1, 1.0, 2.0), c(2, 3.0, 2.5, 2.9), c(3, 2.9, 2.0, 2.0)]
    ex = simulate_exit(candles, 1.0, T0, R, T0 + 600)
    assert ex["why"].startswith("trailing") and 1.9 < ex["x"] < 2.0      # 0.5 at 2x + 0.5 at 2.1x, minus ~4% costs


def test_moonshot_and_time_limit_and_open():
    assert "6x" in simulate_exit([c(1, 2.5, 1.0, 2.4), c(2, 7.0, 3.0, 6.5)], 1.0, T0, R, T0 + 600)["why"]
    flat = [c(i, 1.1, 0.95, 1.05) for i in range(1, 1500)]
    assert simulate_exit(flat, 1.0, T0, R, T0 + 2 * 86400)["why"] == "24h time limit"
    assert simulate_exit(flat[:30], 1.0, T0, R, T0 + 1800) is None        # still open


class Hub:
    def __init__(self, candles):
        self.t, self._c = T0 + 60, candles

    def now(self):
        return self.t

    def candles(self, chain, token, start, end):
        return [x for x in self._c if start <= x[0] <= end]


def test_step_opens_closes_and_never_double_counts(tmp_path):
    alerts = Ledger(tmp_path / "ledger.jsonl")
    alerts.append("alert", T0, {k: v for k, v in alert().items() if k != "ts"})
    alerts.append("alert", T0, {k: v for k, v in alert(id="a-00002", cluster=[]).items() if k != "ts"})
    book = Ledger(tmp_path / "paper.jsonl")
    hub = Hub([c(i, 1.0, 0.5, 0.5) for i in range(2, 10)])
    step(hub, alerts, book)
    s = summary(book, R)
    assert s["open"] == 1 and s["skipped"] == 1 and abs(s["equity_sol"] - 1.0) < 0.01
    hub.t = T0 + 900
    step(hub, alerts, book)
    step(hub, alerts, book)                                   # idempotent
    s = summary(book, R)
    assert s["trades"] == 1 and s["wins"] == 0 and s["equity_sol"] < 0.96
    assert len(state(book, R)["closed"]) == 1 and book.verify().ok
    assert [e["type"] for e in book.entries()].count("paper_open") == 1
