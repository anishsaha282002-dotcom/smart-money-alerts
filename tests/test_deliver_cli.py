import json

import httpx
from typer.testing import CliRunner

from sms import deliver
from sms.cli import app

ALERT = {"id": "a-00001", "story": "🟢 A-grade wallet bought $招财猫\nNot financial advice."}


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_console_prints_the_story():
    lines = []
    assert deliver.Console(out=lines.append).send(ALERT) and "$招财猫" in lines[0]


def test_telegram_sends_plain_text_and_waits_out_one_429():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(429, json={"parameters": {"retry_after": 1}})
        return httpx.Response(200, json={"ok": True})
    tg = deliver.Telegram("TOKEN", "-100123", client=client(handler), sleep=lambda s: None)
    assert tg.send(ALERT) and len(seen) == 2
    assert seen[0]["chat_id"] == "-100123" and seen[0]["text"].startswith(ALERT["story"])
    assert "Alerts only, not advice" in seen[0]["text"] and "parse_mode" not in seen[0]


def test_discord_truncates_and_never_pings():
    seen = []
    dc = deliver.Discord("https://discord.com/api/webhooks/1/x", client=client(
        lambda r: seen.append(json.loads(r.content)) or httpx.Response(204)))
    assert dc.send({"id": "a-1", "story": "x" * 5000})
    assert len(seen[0]["content"]) == 2000 and seen[0]["allowed_mentions"] == {"parse": []}


def test_failed_delivery_is_reported_not_raised():
    def down(request):
        raise httpx.ConnectError("no route")
    assert deliver.Telegram("T", "1", client=client(down)).send(ALERT) is False
    assert deliver.Discord("https://x.test/h", client=client(lambda r: httpx.Response(500))).send(ALERT) is False


def test_channels_are_built_only_from_what_is_configured(settings):
    assert [d.name for d in deliver.from_settings(settings)] == ["console"]
    settings.telegram_bot_token, settings.telegram_chat_id = "t", "1"
    settings.discord_webhook_url = "https://discord.com/api/webhooks/1/x"
    assert [d.name for d in deliver.from_settings(settings)] == ["console", "telegram", "discord"]
    settings.telegram_chat_id = ""
    assert "telegram" not in [d.name for d in deliver.from_settings(settings, console=False)]


# ------------------------------------------------------------------------ CLI

def env(tmp_path):
    return {"SMS_DATA_DIR": str(tmp_path / "data"), "SMS_WEB_DIR": str(tmp_path / "web"),
            "SMS_CONFIG": str(tmp_path / "none.toml"), "COLUMNS": "200"}


def test_cli_demo_then_verify_then_tamper(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["demo"], env=env(tmp_path))
    assert r.exit_code == 0, r.output
    for needle in ("SAMPLE ALERT", "WALLET GRADE:", "CALLER GRADE:", "NARRATIVE:", "PUBLIC RECORD", "hash chain OK",
                   "SYNTHETIC", "Not financial advice"):
        assert needle in r.output
    ledger = tmp_path / "data" / "demo" / "ledger.jsonl"
    site = json.loads((tmp_path / "web" / "data" / "site.json").read_text(encoding="utf-8"))
    assert ledger.exists() and site["meta"]["demo"] and site["alerts"]

    ok = runner.invoke(app, ["verify", str(ledger)], env=env(tmp_path))
    assert ok.exit_code == 0 and "Hash chain OK" in ok.output

    lines = ledger.read_text(encoding="utf-8").split("\n")
    lines[3] = lines[3].replace('"type":"score"', '"type":"score","note":"edited"') if '"type":"score"' in lines[3] \
        else lines[3].replace('"demo":true', '"demo":false')
    ledger.write_text("\n".join(lines), encoding="utf-8")
    bad = runner.invoke(app, ["verify", str(ledger)], env=env(tmp_path))
    assert bad.exit_code == 1 and "chain broken" in bad.output

    rep = runner.invoke(app, ["report", "--demo"], env=env(tmp_path))
    assert rep.exit_code == 0 and "wallet grade" in rep.output


def test_cli_grade_wallet_demo(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["grade-wallet", "nightowl", "--demo"], env=env(tmp_path))
    assert r.exit_code == 0, r.output
    assert "GRADE" in r.output and "closed trades" in r.output and "Score:" in r.output and "synthetic demo wallet" in r.output
    tiny = runner.invoke(app, ["grade-wallet", "freshprince", "--demo"], env=env(tmp_path))
    assert "Tiny sample" in tiny.output and "capped at C" in tiny.output
    missing = runner.invoke(app, ["grade-wallet", "nobody", "--demo"], env=env(tmp_path))
    assert missing.exit_code != 0


def test_cli_verify_missing_ledger_and_sources(tmp_path):
    runner = CliRunner()
    assert runner.invoke(app, ["verify"], env=env(tmp_path)).exit_code == 1
    r = runner.invoke(app, ["sources"], env={**env(tmp_path), "GMGN_API_KEY": "", "HELIUS_API_KEY": ""})
    assert r.exit_code == 0 and "geckoterminal" in r.output and "GMGN_API_KEY" in r.output
