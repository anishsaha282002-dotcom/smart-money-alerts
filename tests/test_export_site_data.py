"""Exporter for the static calls page: public data only, no invented alerts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_site_data.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("export_site_data", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def exp():
    return load_mod()


def _write_ledger(path: Path, records):
    # Minimal JSONL; prev/seq need not be a valid chain for card mapping tests.
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, separators=(",", ":")) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_missing_ledger_writes_empty_alerts_not_fabricated(exp, tmp_path):
    out = tmp_path / "data"
    payload, name = exp.export(root=tmp_path, ledger_path=tmp_path / "missing.jsonl", out_dir=out, include_demo=False)
    assert name == "alerts.json"
    assert payload["alerts"] == []
    assert payload["example"] is False
    assert payload["counts"]["alerts"] == 0
    assert payload["ledger"]["exists"] is False
    saved = json.loads((out / "alerts.json").read_text())
    assert saved["alerts"] == []


def test_demo_rows_excluded_from_alerts_json(exp, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [{
        "type": "alert", "id": "demo1", "demo": True, "seq": 0, "prev": "0" * 64,
        "chain": "solana", "token": "DemoMint", "symbol": "DEMO", "name": "Demo",
        "created": "2026-11-10T04:00:00Z", "created_ts": 1794283200,
        "wallet": "DemoWallet", "wallet_grade": {"grade": "A", "score": 80, "n_closed": 10},
        "text": "SMART-MONEY BUY · $DEMO on Solana", "cobuyers": [], "tags": [],
    }])
    payload, _ = exp.export(root=tmp_path, ledger_path=ledger, out_dir=tmp_path / "out")
    assert payload["alerts"] == []
    assert payload["ledger"]["skipped_demo"] == 1


def test_real_alert_and_score_mapped(exp, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {
            "type": "alert", "id": "abc123", "demo": False, "seq": 0, "prev": "0" * 64,
            "chain": "solana", "token": "So11111111111111111111111111111111111111112",
            "symbol": "REAL", "name": "Real Token",
            "created": "2026-11-10T04:00:00Z", "created_ts": 1794283200,
            "wallet": "CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o",
            "wallet_label": "Cented",
            "wallet_grade": {"grade": "B", "score": 70, "n_closed": 8, "win_rate_shrunk": 0.55},
            "text": "SMART-MONEY BUY · $REAL on Solana",
            "cobuyers": [{"wallet": "OtherWallet111111111111111111111111111111", "grade": "A", "ts": 1794283100}],
            "tags": ["smart"],
            "first_buy_of_token": True,
            "late": {"n": 6, "late_5m": 0.2, "late_30m": 0.05, "late_5m_n": 6, "at_buy": 0.4},
            "caller": {"checked": True, "grade": "B", "posts": 4, "callers": [{"handle": "alice", "grade": "B", "rate": 0.5, "n_eff": 8}]},
            "narrative": {"narrative": "cats", "status": "HOT", "score": 12, "n_tokens": 3, "vol_h1": 1000},
        },
        {
            "type": "score", "alert_id": "abc123", "horizon": "1h", "seq": 1,
            "prev": "x", "ret_from_alert": 0.12, "ret_from_wallet_buy": 0.2,
            "ret_if_5m_late": 0.08, "ret_if_30m_late": 0.01, "max_ret_from_alert": 0.15,
            "scored": "2026-11-10T05:00:00Z",
        },
    ])
    payload, _ = exp.export(root=tmp_path, ledger_path=ledger, out_dir=tmp_path / "out")
    assert payload["counts"]["alerts"] == 1
    card = payload["alerts"][0]
    assert card["symbol"] == "REAL"
    assert card["decision"] == "BUY"
    assert card["sm_confirmed"] is True
    assert card["kol_buy"] is False
    assert card["wallet"]["grade"] == "B"
    assert card["caller"]["grade"] == "B"
    assert card["late"]["late_5m"] == 0.2
    assert card["outcomes"]["1h"]["ret_from_alert"] == 0.12
    assert "first time this wallet" in card["why"][0]
    assert "api_key" not in json.dumps(card)


def test_secrets_stripped_from_export(exp, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [{
        "type": "alert", "id": "sec", "demo": False, "seq": 0, "prev": "0" * 64,
        "chain": "bsc", "token": "0xabc", "symbol": "X", "name": "X",
        "created": "2026-11-10T04:00:00Z", "created_ts": 1,
        "wallet": "0xwallet", "wallet_grade": {"grade": "A", "score": 80, "n_closed": 9},
        "text": "SMART-MONEY SELL · $X on BSC",
        "tags": ["kol"], "cobuyers": [],
        "helius_api_key": "SHOULD_NOT_LEAK",
        "api_key": "nope",
    }])
    payload, _ = exp.export(root=tmp_path, ledger_path=ledger, out_dir=tmp_path / "out")
    blob = json.dumps(payload)
    assert "SHOULD_NOT_LEAK" not in blob
    assert "nope" not in blob
    assert "helius_api_key" not in blob
    assert payload["alerts"][0]["decision"] == "SELL"
    assert payload["alerts"][0]["kol_buy"] is True
    assert payload["alerts"][0]["explorers"]["scan_label"] == "BscScan"


def test_write_sample_sets_example_flag(exp, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [{
        "type": "alert", "id": "d", "demo": True, "seq": 0, "prev": "0" * 64,
        "chain": "solana", "token": "Demo", "symbol": "DEMO", "name": "Demo",
        "created": "2026-11-10T04:00:00Z", "created_ts": 1,
        "wallet": "W", "wallet_grade": {"grade": "A", "score": 80, "n_closed": 9},
        "text": "SMART-MONEY BUY · $DEMO", "tags": [], "cobuyers": [],
    }])
    payload, name = exp.export(root=tmp_path, ledger_path=ledger, out_dir=tmp_path / "out", include_demo=True, example=True)
    assert name == "alerts.sample.json"
    assert payload["example"] is True
    assert "EXAMPLE" in payload["example_note"]
    assert len(payload["alerts"]) == 1
    assert not (tmp_path / "out" / "alerts.json").exists()


def test_callers_and_wallets_summary(exp, tmp_path):
    callers = {
        "_doc": "x",
        "callers": [{"handle": "PoorGoat_", "tier": "A", "note": "public stats", "lang": "en"}],
        "flagged": [{"handle": "bad", "why": "alleged", "lang": "en"}],
        "catalysts": [{"handle": "cz_binance", "note": "catalyst", "lang": "zh/en"}],
    }
    wallets = {
        "wallets": [{"name": "Cented", "chain": "solana", "address": "CyaE1", "tags": ["kol"], "source": "https://example.com"}],
    }
    (tmp_path / "callers.json").write_text(json.dumps(callers))
    (tmp_path / "wallets.json").write_text(json.dumps(wallets))
    cs = exp.summarize_callers(tmp_path / "callers.json")
    ws = exp.summarize_wallets(tmp_path / "wallets.json")
    assert cs["counts"]["callers"] == 1
    assert cs["callers"][0]["handle"] == "PoorGoat_"
    assert ws["wallets"][0]["name"] == "Cented"
    assert "api_key" not in json.dumps(cs) + json.dumps(ws)
