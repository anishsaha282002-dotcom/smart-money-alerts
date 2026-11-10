"""The live hub against a fake network: keyless discovery, graceful failure, optional keys."""
from conftest import FakeNet

from sms.ledger import Ledger
from sms.pipeline import Pipeline
from sms.scoring import score_ledger
from sms.sources.hub import LiveHub
from sms.store import Store

T = 1_794_284_000


def make(settings, clock=None):
    store = Store(":memory:")
    hub = LiveHub(settings, store, clock=clock or (lambda: T))
    return hub, store


def test_keyless_mode_finds_wallet_attributed_trades(fake_net, settings):
    settings.chains = ("bsc",)
    hub, _ = make(settings)
    trades = hub.recent_trades(0)
    assert trades and {t.side for t in trades} == {"buy", "sell"}
    assert all(t.wallet.startswith("0x") and t.source == "geckoterminal" for t in trades)
    hosts = {r.url.host for r in fake_net.requests}
    assert hosts == {"api.geckoterminal.com"}, "no key, so only keyless sources may be contacted"
    assert not hub.gmgn and not hub.helius and not hub.x


def test_status_lists_what_is_on_and_what_each_needs(fake_net, settings):
    hub, _ = make(settings)
    rows = {r["source"]: r for r in hub.status()}
    assert rows["geckoterminal"]["on"] and not rows["gmgn"]["on"] and rows["gmgn"]["needs"] == "GMGN_API_KEY"
    settings.gmgn_api_key = "k"
    assert {r["source"]: r for r in make(settings)[0].status()}["gmgn"]["on"]


def test_token_lookup_gets_a_chartable_pool(fake_net, settings):
    hub, _ = make(settings)
    token = hub.token("bsc", "0x014676D564738f9492217f3cAA702949Cd174444")     # checksummed in, lowercase out
    assert token.symbol == "牛马" and token.address == token.address.lower()
    assert token.pool and ":" not in token.pool, "DexScreener's bonding-curve pair must be replaced by a real pool"
    assert hub.candles("bsc", token, 0, T)


def test_trending_and_narrative_inputs(fake_net, settings):
    hub, _ = make(settings)
    lists = hub.trending("solana")
    assert lists["now"] and lists["base"]
    assert any(t.organic_score is not None for t in lists["now"])              # Jupiter joined in
    assert "chinese" in hub.categories() and hub.narrative_posts() == {}


def test_every_source_down_is_survivable(monkeypatch, settings):
    net = FakeNet(status=503)
    import sms.sources.http as http_mod
    monkeypatch.setattr(http_mod.httpx, "Client", net.client)
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    settings.gmgn_api_key = settings.helius_api_key = settings.x_bearer_token = "k"
    settings.watch_wallets = {"solana": ["WALLET_A"]}
    hub, store = make(settings)
    ledger = Ledger(settings.data_dir / "l.jsonl")
    pipe = Pipeline(hub, settings, store, ledger)
    assert pipe.run_once() == []                      # nothing to say, and no exception
    assert score_ledger(hub, ledger) == {"scores": 0, "copies": 0, "no_data": 0}
    assert hub.token("solana", "x") is None and hub.safety("solana", "x") is None
    assert any(r["failures"] for r in hub.status())
    g, trades = pipe.grade("solana", "WALLET_A")
    assert g.grade == "D" and trades == []


def test_alert_cap_defers_instead_of_dropping(fake_net, settings):
    settings.chains, settings.min_grade, settings.min_buy_usd, settings.max_alerts_per_run = ("bsc",), "D", 0, 1
    hub, store = make(settings)
    pipe = Pipeline(hub, settings, store, Ledger(settings.data_dir / "l.jsonl"))
    store.put("cursor", 0, 0)
    first, second = pipe.run_once(), pipe.run_once()
    assert len(first) == 1 and len(second) == 1, "the buy that did not fit in the first scan is alerted in the second"
    assert first[0]["wallet"]["address"] != second[0]["wallet"]["address"]


def test_with_keys_gmgn_feeds_and_wallet_history_are_used(fake_net, settings):
    settings.gmgn_api_key = "k"
    settings.chains = ("solana",)
    hub, store = make(settings)
    trades = hub.recent_trades(0)
    assert any(t.source == "gmgn" for t in trades)
    wallet = next(t.wallet for t in trades if t.source == "gmgn")
    assert hub.wallet_meta("solana", wallet)["tags"]
    paths = [r.url.path for r in fake_net.requests]
    assert "/v1/user/smartmoney" in paths and "/v1/user/kol" in paths
    assert not any("/pools/" in p and p.endswith("/trades") for p in paths), "GMGN replaces the keyless pool tape"
    hub.wallet_trades("solana", wallet, 0)
    n = len(fake_net.requests)
    hub.wallet_trades("solana", wallet, 0)
    assert len(fake_net.requests) == n, "wallet history is cached between scans"
