from sms.grading import copycheck
from sms.grading.caller import grade_caller, grade_callers
from sms.grading.narrative import classify, has_chinese, momentum
from sms.models import Call, Token

# ------------------------------------------------------------------ callers


def calls(name, xs):
    return [Call(caller=name, chain="solana", token=f"t{i}", ts=1000 + i, x15m=1 + (x - 1) / 2, x1h=x, x24h=x * 0.9)
            for i, x in enumerate(xs)]


def test_good_caller_grades_well_and_bad_caller_badly():
    good = grade_caller(calls("g", [1.4, 1.6, 1.3, 0.9, 1.5, 1.8, 1.2, 1.45, 0.8, 1.7, 1.3, 1.5]))
    bad = grade_caller(calls("b", [0.7, 0.8, 1.1, 0.6, 0.9, 0.5, 0.85, 0.75, 1.05, 0.6]))
    assert good["grade"] in ("A", "B") and bad["grade"] == "D"
    assert good["median_1h"] > 1 > bad["median_1h"] and good["n_calls"] == 12


def test_too_few_aged_calls_is_unrated_not_guessed():
    g = grade_caller(calls("n", [3.0, 4.0]))
    assert g["grade"] is None and g["n_calls"] == 2
    pending = [Call(caller="p", chain="solana", token="t", ts=1)]           # never aged
    assert grade_caller(pending)["n_calls"] == 0


def test_coin_level_caller_grade_and_notes():
    mentions = [Call(caller="g", chain="solana", token="X", ts=50, followers=9000),
                Call(caller="tiny", chain="solana", token="X", ts=60, followers=10),
                Call(caller="new", chain="solana", token="X", ts=70, followers=9000)]
    hist = {"g": calls("g", [1.5] * 10), "new": calls("new", [2.0])}
    cg = grade_callers(mentions, hist, min_followers=2000)
    assert cg.grade in ("A", "B") and cg.n_callers == 2            # the tiny account is ignored
    assert [c["caller"] for c in cg.callers] == ["g", "new"] and cg.callers[1]["grade"] is None
    assert grade_callers([], {}).grade is None
    assert "enough aged calls" in grade_callers(mentions[2:], hist).note


# --------------------------------------------------------------- narratives

def test_chinese_names_and_tickers():
    assert has_chinese("招财猫") and not has_chinese("DOGE")
    assert classify("招财猫", "招财猫") == ["chinese", "animals"]
    assert classify("币安人生", "币安人生") == ["chinese", "binance"]
    assert classify("人工智能币", "AI币")[:2] == ["chinese", "ai"]
    assert classify("Lucky Cat", "招财猫")[0] == "chinese"            # a Chinese ticker is enough


def test_english_classification():
    assert classify("Grok Cat", "GROKCAT") == ["ai", "animals"]
    assert classify("OFFICIAL TRUMP", "TRUMP") == ["politics"]
    assert classify("dogwifhat", "WIF") == ["animals"]
    assert classify("AgentAI", "AGENTAI") == ["ai"]
    assert classify("", "BOTARMY") == ["ai"] and classify("", "SKYNETAI") == ["ai"]
    assert classify("Catalyst", "CTL") == ["other"]                  # not every "cat" is a cat
    assert classify("Samurai", "SAMURAI") == ["other"]               # nor every "ai" an AI
    assert classify("", "") == ["other"]


def tok(name, i=0):
    return Token(chain="solana", address=f"{name}{i}", symbol=name, name=name)


def test_momentum_states():
    base = [tok("PEPE", i) for i in range(6)] + [tok("TRUMP", i) for i in range(3)] + [tok("GAME", 0)]
    now = ([tok("招财猫", i) for i in range(2)] + [tok("PEPE", 9)] + [tok("GROK", i) for i in range(4)]
           + [tok("TRUMP", 9), tok("TRUMP", 8), tok("TRUMP", 7)] + [tok("GAME", 1)])
    # ai was absent all day and is here now -> new; trump share unchanged-ish; pepe collapsing
    r = momentum(now, base)
    assert r["ai"].state == "new" and r["ai"].count_base == 0
    assert r["chinese"].state == "new"
    assert r["animals"].state == "fading"
    assert r["politics"].state == "hot"
    assert r["food"].state == "unknown"
    assert 0 < r["animals"].share_now < r["animals"].share_base


def test_momentum_rising_and_post_counts():
    base = [tok("GROK", 0)] + [tok(f"X{i}") for i in range(9)]
    now = [tok("GROK", i) for i in range(4)] + [tok(f"X{i}") for i in range(6)]
    assert momentum(now, base)["ai"].state == "rising"
    steady = momentum(base, base)
    assert steady["ai"].state == "steady"
    assert momentum(base, base, posts={"ai": (300, 100)})["ai"].state == "rising"
    assert momentum(base, base, posts={"ai": (20, 100)})["ai"].state == "fading"


def test_same_token_in_a_list_twice_counts_once():
    t = tok("GROK")
    r = momentum([t, t, tok("X")], [t, tok("X")])
    assert r["ai"].count_now == 1


# --------------------------------------------------------------- copy check

def candles(points, t0=10_000):
    """points: {minute: price}; linear in between; one candle per minute."""
    mins = sorted(points)
    out = []
    for a, b in zip(mins, mins[1:]):
        for m in range(a, b):
            p = points[a] + (points[b] - points[a]) * (m - a) / (b - a)
            out.append([t0 + m * 60, p, p * 1.001, p * 0.999, p, 100.0])
    out.append([t0 + mins[-1] * 60, points[mins[-1]], points[mins[-1]], points[mins[-1]], points[mins[-1]], 100.0])
    return out


def test_slow_runner_still_copyable():
    c = copycheck.copy_check(candles({0: 1.0, 120: 4.0, 240: 3.0}), 10_000, 1.0)
    assert c["verdict"] == "mostly-there" and c["complete"]
    assert 1.0 < c["5m"]["entry_x"] < 1.2 and c["5m"]["kept"] > 0.8
    assert c["30m"]["kept"] < c["5m"]["kept"] and abs(c["wallet_x"] - 4.0) < 0.05
    assert c["spark"][0] == 1.0 and len(c["spark"]) <= 41


def test_spike_is_mostly_gone_in_five_minutes():
    c = copycheck.copy_check(candles({0: 1.0, 3: 3.5, 6: 1.3, 240: 1.2}), 10_000, 1.0)
    assert c["verdict"] == "mostly-gone" and c["5m"]["kept"] < 0.25
    assert c["wallet_x"] > 3


def test_buy_that_never_ran():
    c = copycheck.copy_check(candles({0: 1.0, 240: 0.4}), 10_000, 1.0)
    assert c["verdict"] == "never-ran" and c["5m"]["kept"] is None


def test_not_enough_data_says_nothing():
    assert copycheck.copy_check([], 10_000, 1.0) is None
    assert copycheck.copy_check(candles({0: 1.0, 10: 1.1}), 10_000, 1.0) is None
    assert copycheck.copy_check(candles({0: 1.0, 240: 2.0}), 10_000, None) is None
    assert copycheck.copy_check(candles({0: 1.0, 240: 2.0}), 10_000, 1.0, now=10_000 + 600) is None


def test_history_summary_keeps_the_duds():
    runner = copycheck.copy_check(candles({0: 1.0, 120: 4.0, 240: 3.0}), 10_000, 1.0)
    spike = copycheck.copy_check(candles({0: 1.0, 3: 3.5, 6: 1.3, 240: 1.2}), 10_000, 1.0)
    dud = copycheck.copy_check(candles({0: 1.0, 240: 0.4}), 10_000, 1.0)
    s = copycheck.summarize([runner, spike, dud, None])
    assert s["n"] == 3 and s["n_ran"] == 2 and s["verdict"] in ("mostly-there", "partly-gone", "mostly-gone")
    assert copycheck.summarize([dud])["verdict"] == "never-ran"
    assert copycheck.summarize([]) is None
