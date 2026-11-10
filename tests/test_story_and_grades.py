from sma import story
from sma.grading import caller, narrative


def alert(**kw):
    a = {"chain": "solana", "symbol": "TEST", "wallet": "WalletAddress1234567890", "wallet_label": "", "seq_hint": 3,
         "created_ts": 1000, "buy_ts": 580, "buy_usd": 2400,
         "wallet_grade": {"grade": "A", "score": 80, "n_closed": 14, "wins": 11, "last10_wins": 8, "last10_n": 10,
                          "window_days": 30, "win_rate_shrunk": 0.68, "median_return": 0.46, "median_hold_s": 2400,
                          "warnings": [], "flags": [], "data_source": "helius"},
         "late": {"n": 9, "at_buy": 0.46, "late_5m": 0.21, "late_30m": -0.04, "late_5m_n": 9, "too_fast_5m": 2},
         "forward": {"moved_since_buy": 0.12, "minutes_since_buy": 7},
         "caller": caller.NOT_CHECKED, "narrative": {"narrative": "AI/agents", "status": "RISING", "score": 18.2,
                                                     "n_tokens": 14, "vol_h1": 1.2e6},
         "liq": 48000, "mcap": 900000, "first_buy_of_token": True, "cobuyers": [{"grade": "B"}], "token_age_s": 3 * 3600}
    a.update(kw)
    return a


def test_story_has_all_required_parts():
    t = story.render(alert())
    for s in ("grade A", "won 8 of last 10 closed trades over 30d", "n=14 closed", "Why it's interesting",
              "5 min late +21%", "30 min late -4%", "+12% since its buy", "Caller chatter: not checked",
              "AI/agents — RISING", "Not financial advice", "within 5 min on 2"):
        assert s in t, s


def test_low_sample_warning_shown():
    a = alert()
    a["wallet_grade"]["warnings"] = ["LOW SAMPLE: only 4 closed trades - grade capped at C; treat it as a guess"]
    assert "⚠ LOW SAMPLE" in story.render(a)


def test_copy_verdicts():
    assert "NOT worth" in story.copy_verdict({"late_5m": -0.05, "late_5m_n": 5})
    assert "not enough" in story.copy_verdict({"late_5m": 0.5, "late_5m_n": 2})


def test_caller_prior_parse_and_grade():
    cs = caller.load_callers({"callers": [{"handle": "Alpha", "note": "92% of 25"}, {"handle": "Zh", "lang": "zh", "note": "none"}]})
    assert cs["alpha"]["prior"] == (0.92, 25)
    r = caller.grade_chatter([{"author": "alpha", "ts": 1}, {"author": "rando", "ts": 2}], cs)
    assert r["checked"] and r["callers"][0]["handle"] == "Alpha" and r["grade"] in ("A", "B")
    # tracked outcomes dominate the prior as they accumulate
    rate_bad, _ = caller.caller_rate(cs["alpha"], tracked_hits=0, tracked_n=60)
    assert caller.rate_grade(rate_bad) == "D"


def test_narrative_chinese_and_english_clusters():
    toks = [{"chain": "bsc", "address": f"0x{i}", "name": n, "symbol": n, "vol_h1": 1000, "sources": ["gecko_fourmeme"]}
            for i, n in enumerate(["牛逼", "修仙人生", "发财"])]
    toks += [{"chain": "solana", "address": f"S{i}", "name": n, "symbol": n, "vol_h1": 5000, "sources": ["jup_trending"]}
             for i, n in enumerate(["gpt agent", "ai dog", "robot"])]
    ranked, tmap = narrative.cluster_and_score(toks, now_ts=0)
    names = {r["narrative"] for r in ranked}
    assert "Chinese-culture" in names and "AI/agents" in names
    st, _ = narrative.label(ranked[0], [(ranked[0]["score"] / 2, 1)])
    assert st in ("RISING", "HOT")


def test_llm_narration_optional_and_guarded(monkeypatch):
    from sma import http
    t = story.render(alert())
    assert story.narrate_llm(t, {}, {}) == t                     # no key: template kept, no call
    monkeypatch.setattr(http, "post_json", lambda *a, **k: {"choices": [{"message": {"content": "Great buy, +99%!"}}]})
    assert story.narrate_llm(t, {}, {"LLM_API_KEY": "k"}) == t   # model changed numbers: template kept


def test_notify_console_only_without_env():
    out = []
    from sma.notify import deliver
    assert deliver("hello", {}, log=out.append) == ["console"] and out[0] == "hello"
