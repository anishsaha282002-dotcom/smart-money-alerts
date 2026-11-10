"""Always-on server pieces: stream trades reach the scanner, health is reported, publish pushes."""
import subprocess
import time

from sms.sources.helius_stream import SwapStore
from sms.sources.hub import LiveHub
from sms.store import Store
from sms import publish as pub
from sms.models import Token


def hub_with_store(settings, tmp_path, fresh=True):
    settings.helius_api_key = "test-key"
    settings.data_dir = tmp_path
    hub = LiveHub(settings, Store(":memory:"))
    st = hub.helius.store
    if fresh:
        st.heartbeat(method="parsedTransactionSubscribe", wallets=837, last_event_ts=int(time.time()))
    return hub, st


def test_stream_trades_feed_the_scanner_with_an_estimated_value(settings, tmp_path, monkeypatch):
    hub, st = hub_with_store(settings, tmp_path)
    now = int(time.time())
    st.insert_many([
        {"signature": "S1", "wallet": "W1", "mint": "COIN", "side": "buy", "amount": 1000.0, "timestamp": now - 10,
         "source": "stream", "name": "nightowl", "type": "SWAP", "tags": []},
        {"signature": "S2", "wallet": "W1", "mint": "COIN", "side": "sell", "amount": 400.0, "timestamp": now - 5,
         "source": "stream", "name": "", "type": "SWAP", "tags": []},
    ])
    monkeypatch.setattr(hub, "token", lambda chain, addr: Token(chain=chain, address=addr, symbol="COIN", price_usd=2.0))
    trades = {t.side: t for t in hub._stream_trades(now - 60)}
    assert trades["buy"].usd == 2000.0 and trades["buy"].source == "helius_stream~price" and trades["buy"].symbol == "COIN"
    assert trades["sell"].usd == 0.0
    assert hub.wallet_meta("solana", "W1")["name"] == "nightowl"
    assert hub._stream_trades(now) == []          # nothing newer than the cursor


def test_stale_worker_is_ignored(settings, tmp_path):
    hub, st = hub_with_store(settings, tmp_path, fresh=False)
    st.insert_many([{"signature": "S", "wallet": "W", "mint": "C", "side": "buy", "amount": 1.0,
                     "timestamp": int(time.time()), "source": "stream", "name": "", "type": "SWAP", "tags": []}])
    assert hub._stream_trades(0) == []
    assert hub.worker_health() is None            # never ran here: the site shows "not running"


def test_worker_health_reports_the_heartbeat(settings, tmp_path):
    hub, _ = hub_with_store(settings, tmp_path)
    h = hub.worker_health()
    assert h["fresh"] and h["running"] and h["wallets"] == 837 and h["method"] == "parsedTransactionSubscribe"
    assert h["heartbeat_ts"] and h["last_event_ts"]


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_publish_commits_record_and_site_data_and_pushes(settings, tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "smart-money-stories", str(remote))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "smart-money-stories")
    git(work, "remote", "add", "origin", str(remote))
    (work / "README.md").write_text("x")
    git(work, "add", ".")
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git(work, "push", "-q", "origin", "smart-money-stories")

    settings.github_token = "github_pat_" + "x" * 30
    assert pub.publish(settings, root=work) == "nothing to publish yet"
    (work / "record").mkdir()
    (work / "record" / "ledger.jsonl").write_text('{"seq":0}\n')
    (work / "web" / "data").mkdir(parents=True)
    (work / "web" / "data" / "site.json").write_text("{}")
    assert pub.publish(settings, root=work).startswith("published")
    log = subprocess.run(["git", "log", "--oneline", "smart-money-stories"], cwd=remote, capture_output=True, text=True).stdout
    assert "live:" in log
    assert pub.publish(settings, root=work) == "no changes since the last publish"
    cfg = (work / ".git" / "config").read_text()
    assert "github_pat_" not in cfg and "extraheader" not in cfg, "the token must never be saved"


def test_publish_without_a_token_refuses(settings, tmp_path):
    settings.github_token = ""
    try:
        pub.publish(settings, root=tmp_path)
    except pub.PublishError as e:
        assert "GITHUB_TOKEN" in str(e)
    else:
        raise AssertionError("expected PublishError")


def test_errors_never_show_the_token():
    tok = "github_pat_" + "a" * 40
    assert tok not in pub._redact(f"fatal: could not read from https://x:{tok}@github.com", tok)
    assert "ghp_" + "b" * 36 not in pub._redact("token ghp_" + "b" * 36, "")


def test_deploy_files_hold_no_secrets_and_point_at_real_commands():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "deploy"
    text = "\n".join(p.read_text() for p in root.iterdir() if p.is_file())
    for cmd in ("sms stream", "sms watch", "sms publish", "EnvironmentFile=__DIR__/.env"):
        assert cmd in text
    assert "HELIUS_STREAM_DB=__DIR__/record/helius_swaps.db" in text
    import re
    assert not re.search(r"(api-key=|github_pat_|ghp_)[A-Za-z0-9]{8,}", text)
