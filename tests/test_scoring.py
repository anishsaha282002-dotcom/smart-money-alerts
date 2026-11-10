from sms.ledger import Ledger
from sms.models import Token
from sms.report import collect, stats, text
from sms.scoring import score_calls, score_ledger
from sms.models import Call
from sms.store import Store

T0 = 1_000_000


class FakeHub:
    demo = False

    def __init__(self, candles):
        self.t, self._candles = T0, candles

    def now(self):
        return self.t

    def candles(self, chain, token, start, end):
        return [c for c in self._candles.get(token.address, []) if start <= c[0] <= end]

    def token(self, chain, address):
        return Token(chain=chain, address=address, pool="p")


def minute_candles(prices, start=T0 - 120):
    return [[start + i * 60, p, p * 1.01, p * 0.99, p, 10.0] for i, p in enumerate(prices)]


def alert(ledger, token, ts=T0, entry=1.0):
    return ledger.append("alert", ts, {
        "id": ledger.next_alert_id(), "chain": "solana", "entry_price": entry,
        "token": {"address": token, "symbol": token.upper(), "pool": "p"},
        "buy": {"ts": ts - 60, "price": entry * 0.97},
        "grades": {"wallet": {"grade": "A"}, "caller": {"grade": None}, "narrative": {"state": "hot", "label": "AI"}}})


def test_scores_are_appended_when_due_and_never_twice(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    hub = FakeHub({"up": minute_candles([1.0 + i * 0.001 for i in range(1500)])})
    a = alert(ledger, "up")
    alert_line = ledger.path.read_text(encoding="utf-8").split("\n")[0]

    assert score_ledger(hub, ledger)["scores"] == 0            # nothing is due at alert time
    hub.t = T0 + 20 * 60
    assert score_ledger(hub, ledger)["scores"] == 1            # +15m
    hub.t = T0 + 5 * 3600
    assert score_ledger(hub, ledger) == {"scores": 2, "copies": 1, "no_data": 0}      # +1h, +4h and the copy check
    assert score_ledger(hub, ledger)["scores"] == 0            # idempotent
    hub.t = T0 + 25 * 3600
    assert score_ledger(hub, ledger)["scores"] == 1            # +24h

    scores = {e["h"]: e for e in ledger.entries("score")}
    assert set(scores) == {"15m", "1h", "4h", "24h"} and all(e["alert_id"] == a["id"] for e in scores.values())
    assert 1.0 < scores["15m"]["x"] < scores["1h"]["x"] < scores["4h"]["x"]
    assert scores["1h"]["peak_x"] >= scores["1h"]["x"] >= scores["1h"]["low_x"] and scores["1h"]["status"] == "ok"
    assert ledger.verify().ok
    assert ledger.path.read_text(encoding="utf-8").split("\n")[0] == alert_line, "the alert line is never rewritten"


def test_a_dead_pool_is_recorded_as_quiet_and_counts_as_a_miss(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    # trades for ten minutes, a collapse, then silence
    hub = FakeHub({"rug": minute_candles([1.0] * 8 + [0.3, 0.05, 0.04, 0.04])})
    alert(ledger, "rug")
    hub.t = T0 + 5 * 3600
    score_ledger(hub, ledger)
    s = {e["h"]: e for e in ledger.entries("score")}
    assert s["15m"]["status"] == "ok" and s["15m"]["x"] < 0.1
    assert s["4h"]["status"] == "quiet" and s["4h"]["x"] < 0.1
    row = stats(ledger)["overall"]["h"]["4h"]
    assert row["measured"] == 1 and row["hits"] == 0 and row["quiet"] == 1


def test_no_data_is_written_down_only_after_giving_it_time(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    hub = FakeHub({})
    alert(ledger, "ghost")
    hub.t = T0 + 3600 + 60
    assert score_ledger(hub, ledger) == {"scores": 0, "copies": 0, "no_data": 0}       # maybe the candles are late
    hub.t = T0 + 8 * 3600
    assert score_ledger(hub, ledger)["no_data"] == 2                                  # 15m and 1h given up on
    e = ledger.entries("score")[0]
    assert e["status"] == "no_data" and e["x"] is None
    row = stats(ledger)["overall"]["h"]["1h"]
    assert row["no_data"] == 1 and row["measured"] == 0 and row["hit_rate"] is None


def test_report_counts_hits_misses_and_pending(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    hub = FakeHub({"up": minute_candles([1.0 + i * 0.002 for i in range(400)]),
                   "down": minute_candles([1.0 - i * 0.002 for i in range(400)])})
    alert(ledger, "up")
    alert(ledger, "down")
    alert(ledger, "up", ts=T0 + 3000)                # too young for +1h below
    hub.t = T0 + 3700
    score_ledger(hub, ledger)
    s = stats(ledger)
    hour = s["by_wallet_grade"]["A"]["h"]["1h"]
    assert hour["measured"] == 2 and hour["hits"] == 1 and hour["pending"] == 1 and hour["hit_rate"] == 0.5
    assert s["n_misses"] >= 1 and s["misses"][0]["symbol"] == "DOWN" and s["head"] == ledger.head
    assert len(s["curve"]) == 2
    out = text(s)
    assert "1/2" in out and "$DOWN" in out and "Not financial advice" in out
    merged = collect(ledger)
    assert len(merged) == 3 and "1h" in merged[0]["scores"] and "1h" not in merged[2]["scores"]


def test_caller_mentions_are_aged_once(tmp_path):
    store = Store(":memory:")
    hub = FakeHub({"tok": minute_candles([1.0 + i * 0.001 for i in range(1500)], start=T0 - 300)})
    store.add_calls([Call(caller="sage", chain="solana", token="tok", ts=T0),
                     Call(caller="sage", chain="solana", token="gone", ts=T0)])
    hub.t = T0 + 3600
    assert score_calls(hub, store) == 0                     # not a day old yet
    hub.t = T0 + 90000
    assert score_calls(hub, store) == 2 and score_calls(hub, store) == 0
    aged = {c.token: c for c in store.caller_history("sage", hub.t)}
    assert 1.0 < aged["tok"].x15m < aged["tok"].x1h < aged["tok"].x24h
    assert aged["gone"].x1h is None                          # no candles: stays unrated, is not retried
