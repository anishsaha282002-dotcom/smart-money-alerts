"""The whole product on the bundled synthetic world: scan -> ledger -> scoring -> report -> site."""
import json

import pytest

from sms import demo, report
from sms.ledger import Ledger, verify_text
from sms.models import GRADES, HORIZONS
from sms.store import Store


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from sms import config
    tmp = tmp_path_factory.mktemp("demo")
    s = config.load(environ={"SMS_CONFIG": str(tmp / "none.toml")})
    s.data_dir, s.web_dir = tmp / "data", tmp / "web"
    s.min_grade, s.chains = "C", ("solana", "bsc", "base")
    ledger, store = Ledger(s.data_dir / "ledger.jsonl"), Store(":memory:")
    out = demo.run(s, ledger, store)
    return {"settings": s, "ledger": ledger, "store": store, **out}


def test_demo_produces_alerts_on_every_chain(world):
    alerts = world["alerts"]
    assert len(alerts) > 40
    assert {a["chain"] for a in alerts} == {"solana", "bsc", "base"}
    assert any(a["token"]["launchpad"] == "four.meme" for a in alerts)
    assert any(any("一" <= ch <= "鿿" for ch in a["token"]["symbol"]) for a in alerts)
    assert all(a["demo"] and "SYNTHETIC DEMO DATA" in a["story"] for a in alerts)


def test_every_alert_carries_three_separate_grades_and_a_story(world):
    for a in world["alerts"]:
        g = a["grades"]
        assert set(g) == {"wallet", "caller", "narrative"}
        assert g["wallet"]["grade"] in GRADES and g["caller"]["grade"] in (*GRADES, None)
        assert g["narrative"]["state"] in ("new", "rising", "hot", "fading", "steady", "unknown")
        for heading in ("WALLET GRADE:", "CALLER GRADE:", "NARRATIVE:", "CAN YOU STILL COPY IT?", "Not financial advice"):
            assert heading in a["story"]
        assert "score" not in a or isinstance(a.get("score"), type(None)), "no blended overall score"
        assert a["entry_price"] and a["buy"]["usd"] >= world["settings"].min_buy_usd


def test_low_graded_and_flagged_wallets_do_not_alert(world):
    labels = {a["wallet"]["label"] for a in world["alerts"]}
    assert "bagholder_joe" not in labels                        # graded D
    assert all(a["grades"]["wallet"]["grade"] != "D" for a in world["alerts"])
    board = {w["label"] or w["wallet"]: w for w in report.leaderboard(world["store"])}
    bot = next(w for w in board.values() if "bot" in w["flags"])
    assert bot["grade"] == "D" and bot["wallet"] not in {a["wallet"]["address"] for a in world["alerts"]}


def test_small_sample_alert_is_capped_and_warned(world):
    a = next(a for a in world["alerts"] if a["wallet"]["label"] == "freshprince")
    w = a["grades"]["wallet"]
    assert w["n_closed"] == 4 and w["grade"] == "C" and w["capped"] and w["small_sample"]
    assert "⚠ Tiny sample: only 4 closed trades" in a["story"]


def test_cluster_narrative_and_caller_reasons_appear(world):
    cat = [a for a in world["alerts"] if a["token"]["symbol"] == "招财猫"]
    assert len(cat) == 3 and [len(a["cluster"]) for a in cat] == [0, 1, 2]
    kinds = {r["kind"] for a in cat for r in a["reasons"]}
    assert {"cluster", "narrative", "early", "caller"} <= kinds
    assert cat[-1]["grades"]["narrative"]["key"] == "chinese" and cat[-1]["grades"]["narrative"]["state"] == "rising"
    assert cat[-1]["grades"]["caller"]["n_callers"] == 2


def test_ledger_is_valid_scored_and_reproducible(world, tmp_path):
    ledger = world["ledger"]
    v = verify_text(ledger.path.read_text(encoding="utf-8"))
    assert v.ok and v.head == ledger.head
    types = {e["type"] for e in ledger.entries()}
    assert types == {"alert", "score", "copy", "anchor"}
    assert {e["h"] for e in ledger.entries("score")} == set(HORIZONS)
    assert {e["status"] for e in ledger.entries("score")} >= {"ok", "quiet"}       # rugs show up as quiet
    # same scenario, same seed -> the same ledger, byte for byte
    again = Ledger(tmp_path / "again.jsonl")
    demo.run(world["settings"], again, Store(":memory:"))
    assert again.head == ledger.head


def test_record_includes_misses_and_pending(world):
    s = report.stats(world["ledger"])
    assert s["alerts"] == len(world["alerts"]) and s["n_misses"] > 5 and s["misses"]
    assert any(m["x"] < 0.2 for m in s["misses"]), "the rug has to be on the record"
    assert sum(s["by_wallet_grade"][g]["n"] for g in GRADES) == s["alerts"]
    newest = max(world["alerts"], key=lambda a: a["ts"])
    assert s["overall"]["h"]["24h"]["pending"] >= 1 and s["overall"]["h"]["15m"]["pending"] >= 1
    assert newest["id"] not in {e["alert_id"] for e in world["ledger"].entries("score")}
    assert set(s["copy_verdicts"]) >= {"mostly-there", "mostly-gone"}


def test_site_export_has_everything_the_website_reads(world):
    out = report.export(world["ledger"], world["store"], world["hub"], world["settings"])
    site = json.loads((out / "site.json").read_text(encoding="utf-8"))
    assert set(site) == {"meta", "ticker", "alerts", "narratives", "wallets", "stats", "baserates"}
    assert site["meta"]["demo"] is True and site["meta"]["head"] == world["ledger"].head
    assert "Not financial advice" in site["meta"]["disclaimer"]
    assert site["ticker"] and site["alerts"][0]["ts"] >= site["alerts"][-1]["ts"]
    scored = next(a for a in site["alerts"] if a["copy"] and a["scores"])
    assert scored["copy"]["spark"] and scored["copy"]["verdict"]
    assert {n["state"] for n in site["narratives"]} >= {"new", "rising", "hot", "fading"}
    assert [w["score"] for w in site["wallets"]] == sorted((w["score"] for w in site["wallets"]), reverse=True)
    assert (out / "ledger.jsonl").read_bytes() == world["ledger"].path.read_bytes()


def test_cooldown_stops_repeat_alerts(world):
    seen = {}
    for a in world["alerts"]:
        key = (a["wallet"]["address"], a["token"]["address"])
        assert key not in seen or a["ts"] - seen[key] >= world["settings"].cooldown_hours * 3600
        seen[key] = a["ts"]
