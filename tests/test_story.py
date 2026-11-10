from types import SimpleNamespace

from sms import story


def alert(**over):
    a = {
        "id": "a-00042", "chain": "bsc", "demo": False,
        "token": {"address": "0xabc", "symbol": "招财猫", "name": "招财猫", "launchpad": "four.meme"},
        "wallet": {"address": "0x7a3f00000000000000000000000000000000c21e", "label": "猫王"},
        "buy": {"ts": 1000, "usd": 2400.0, "price": 0.0005, "tx": "0x1", "age_s": 840, "size_x": 2.3},
        "entry_price": 0.00052, "mcap_usd": 182000,
        "grades": {
            "wallet": {"grade": "A", "score": 81, "n_closed": 23, "wins": 17, "last10_wins": 8, "last10_n": 10,
                       "win_rate": 0.739, "win_rate_shrunk": 0.667, "pnl_usd": 41200.0, "roi": 0.8,
                       "median_hold_s": 11400, "flags": [], "small_sample": False, "capped": False, "days": 30},
            "caller": {"grade": "B", "n_callers": 1, "note": "", "callers": [
                {"caller": "bnb_hunter", "grade": "B", "score": 60, "n_calls": 14, "median_15m": 1.12,
                 "median_1h": 1.38, "median_24h": 1.05}]},
            "narrative": {"key": "chinese", "label": "Chinese memes", "state": "rising", "share_now": 0.18,
                          "share_base": 0.09, "posts_now": None},
        },
        "copy_hist": {"n": 6, "n_ran": 5, "wallet_x": 2.4, "verdict": "partly-gone",
                      "5m": {"entry_x": 1.21, "left_x": 1.9, "kept": 0.62}, "30m": {"entry_x": 1.8, "left_x": 1.2, "kept": 0.21}},
        "cluster": [], "safety": None,
        "reasons": [{"kind": "cluster", "text": "Cluster: 2 other graded wallets (A, B) bought it in the 30 minutes before."}],
    }
    a.update(over)
    return a


def test_story_has_the_three_grades_as_separate_sections():
    text = story.render(alert())
    for heading in ("WALLET GRADE: A (81/100)", "CALLER GRADE: B", "NARRATIVE: Chinese memes", "CAN YOU STILL COPY IT?"):
        assert heading in text
    assert text.index("WALLET GRADE") < text.index("CALLER GRADE") < text.index("NARRATIVE:") < text.index("CAN YOU STILL")
    assert "Won 8 of its last 10 closed trades in 30 days" in text
    assert "$招财猫" in text and "BNB Chain · four.meme" in text and "猫王" in text
    assert "Not financial advice" in text and "a-00042" in text
    assert "overall score" not in text.lower()          # the grades are never blended into one number


def test_story_is_deterministic():
    assert story.render(alert()) == story.render(alert())


def test_sample_size_warnings():
    def w(**kw):
        a = alert()
        a["grades"]["wallet"].update(kw)
        return story.render(a)
    assert "⚠" not in w().split("CALLER GRADE")[0].split("WALLET GRADE")[1]
    assert "⚠ Small sample: 7 closed trades" in w(n_closed=7, small_sample=True)
    assert "⚠ Tiny sample: only 3 closed trades" in w(n_closed=3, small_sample=True, capped=True, grade="C")
    assert "capped at C" in w(n_closed=3, small_sample=True, capped=True, grade="C")
    assert "⚠ No closed trades" in w(n_closed=0, small_sample=True, last10_n=0, last10_wins=0)


def test_cold_streak_is_called_out_even_when_the_grade_is_good():
    a = alert()
    a["grades"]["wallet"].update(last10_wins=3)
    assert "⚠ Cold streak" in story.render(a) and "only 3 of its last 10" in story.render(a)
    assert "Cold streak" not in story.render(alert())


def test_flags_and_safety_are_spelled_out():
    a = alert(safety={"source": "goplus", "risks": ["sell tax 25%"]})
    a["grades"]["wallet"].update(flags=["sniper"], grade="B")
    text = story.render(a)
    assert "snipes launches" in text and "⚠ SAFETY: sell tax 25%." in text


def test_copy_check_is_honest_when_the_answer_is_bad():
    gone = alert(copy_hist={"n": 5, "n_ran": 4, "wallet_x": 3.0, "verdict": "mostly-gone",
                            "5m": {"entry_x": 1.9, "left_x": 1.1, "kept": 0.08}, "30m": {"entry_x": 1.2, "left_x": 1.0, "kept": 0.0}})
    text = story.render(gone)
    assert "mostly gone within 5 minutes" in text and "has usually not paid" in text
    assert "No history yet" in story.render(alert(copy_hist=None))
    assert "best cases" in story.render(alert())


def test_no_callers_and_quiet_narrative():
    a = alert()
    a["grades"]["caller"] = {"grade": None, "n_callers": 0, "callers": [], "note": "No tracked caller has mentioned it yet."}
    a["grades"]["narrative"].update(state="unknown")
    text = story.render(a)
    assert "CALLER GRADE: none yet" in text and "No tracked caller" in text and "QUIET" in text


def test_demo_alerts_say_so():
    assert "SYNTHETIC DEMO DATA" in story.render(alert(demo=True))


# ------------------------------------------------------------- LLM rewording

class FakeClaude:
    """Stands in for anthropic.Anthropic(): returns whatever text it was built with."""

    def __init__(self, text, stop_reason="end_turn", fail=False):
        self.kwargs = None
        outer = self

        class Messages:
            def create(self, **kwargs):
                outer.kwargs = kwargs
                if fail:
                    raise RuntimeError("boom")
                return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
        self.beta = SimpleNamespace(messages=Messages())


def test_rewording_is_off_by_default(settings):
    text = story.render(alert())
    assert not settings.llm_reword
    assert story.reword(text, settings, client=FakeClaude("changed")) == text


def test_reworded_text_is_used_only_if_every_fact_survives(settings):
    settings.llm_reword = True
    text = story.render(alert())
    ok = text.replace("Won 8 of its last 10 closed trades", "It has won 8 of its last 10 closed trades")
    fake = FakeClaude(ok)
    assert story.reword(text, settings, client=fake) == ok
    assert fake.kwargs["model"] == settings.llm_model and fake.kwargs["messages"][0]["content"] == text

    for bad in (text.replace("Won 8 of", "Won 9 of"),               # a changed number
                text.replace("$招财猫", "$LUCKYCAT"),                 # a changed ticker
                text.replace("WALLET GRADE: A", "WALLET GRADE: B"),  # a changed grade
                text + "\nExpect 500% soon.",                        # an invented number
                text.replace("Not financial advice. This tool cannot trade.", ""),
                ""):
        assert story.reword(text, settings, client=FakeClaude(bad)) == text


def test_rewording_failures_fall_back_to_the_template(settings):
    settings.llm_reword = True
    text = story.render(alert())
    assert story.reword(text, settings, client=FakeClaude("x", fail=True)) == text
    assert story.reword(text, settings, client=FakeClaude(text, stop_reason="refusal")) == text
