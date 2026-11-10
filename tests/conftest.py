"""Shared test helpers. The whole suite is offline: every source is exercised through a stored
fixture or a fake transport, and a guard fails any test that reaches for the real network."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from sms import config
from sms.models import Trade

FIXTURES = Path(__file__).parent / "fixtures"
RealClient = httpx.Client          # kept before any test swaps httpx.Client for the fake network
NOW = 1_794_300_000
DAY = 86400


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture():
    return load


@pytest.fixture
def settings(tmp_path):
    s = config.load(environ={"SMS_CONFIG": str(tmp_path / "none.toml")})
    s.data_dir, s.web_dir = tmp_path / "data", tmp_path / "web"
    return s


def round_trip(wallet="W", token="T1", buy_ts=NOW - 5 * DAY, hold=3600, cost=1000.0, roi=0.5, chain="solana",
               symbol="DOGE", created_ts=None) -> list[Trade]:
    """A buy and the sell that closes it."""
    common = dict(chain=chain, wallet=wallet, token=token, token_amount=1_000_000.0, symbol=symbol,
                  token_created_ts=created_ts)
    return [Trade(side="buy", ts=buy_ts, usd=cost, price_usd=cost / 1e6, tx=f"{token}-b-{buy_ts}", **common),
            Trade(side="sell", ts=buy_ts + hold, usd=cost * (1 + roi), price_usd=cost * (1 + roi) / 1e6,
                  tx=f"{token}-s-{buy_ts}", **common)]


def history(n_win: int, n_loss: int, win_roi=0.8, loss_roi=-0.4, hold=3 * 3600, **kw) -> list[Trade]:
    out = []
    for i in range(n_win + n_loss):
        roi = win_roi * (1 + (i % 4) * 0.25) if i < n_win else loss_roi
        out += round_trip(token=f"T{i}", buy_ts=NOW - (i + 1) * 20000, hold=hold, roi=roi, **kw)
    return out


@pytest.fixture
def make_history():
    return history


@pytest.fixture
def make_round_trip():
    return round_trip


# ------------------------------------------------------------------ fake network

ROUTES = [
    (r"api\.geckoterminal\.com/.*/trending_pools", "gt_trending_solana.json"),
    (r"api\.geckoterminal\.com/.*/dexes/four-meme/pools", "gt_four_meme_pools.json"),
    (r"api\.geckoterminal\.com/.*/new_pools", "gt_four_meme_pools.json"),
    (r"api\.geckoterminal\.com/.*/tokens/[^/]+/pools", "gt_four_meme_pools.json"),
    (r"api\.geckoterminal\.com/.*/pools/[^/]+/trades", "gt_pool_trades.json"),
    (r"api\.geckoterminal\.com/.*/ohlcv/", "gt_ohlcv.json"),
    (r"api\.dexscreener\.com/tokens/v1/", "dexscreener_token.json"),
    (r"api\.dexscreener\.com/token-boosts", "dexscreener_boosts.json"),
    (r"lite-api\.jup\.ag/tokens/v2/toptrending", "jupiter_trending.json"),
    (r"api\.coingecko\.com/.*/coins/categories", "coingecko_categories.json"),
    (r"api\.rugcheck\.xyz/", "rugcheck_summary.json"),
    (r"api\.gopluslabs\.io/", "goplus_token.json"),
    (r"openapi\.gmgn\.ai/v1/user/(smartmoney|kol)", "gmgn_smartmoney.json"),
    (r"openapi\.gmgn\.ai/v1/user/wallet_activity", "gmgn_activity.json"),
    (r"openapi\.gmgn\.ai/v1/callout/global", "gmgn_callouts.json"),
    (r"api\.helius\.xyz/v0/addresses/", "helius_swaps.json"),
    (r"api\.x\.com/2/tweets/search/recent", "x_search.json"),
]


class FakeNet:
    """Stands in for the internet: serves fixtures by URL and remembers every request made."""

    def __init__(self, status: int | None = None):
        self.requests: list[httpx.Request] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status:
            return httpx.Response(self.status, json={"error": "simulated outage"})
        url = f"{request.url.host}{request.url.path}"
        for pattern, name in ROUTES:
            if re.search(pattern, url):
                return httpx.Response(200, json=load(name))
        return httpx.Response(404, json={"error": "no fixture"})

    def client(self, *a, **k) -> httpx.Client:
        return RealClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake_net(monkeypatch):
    net = FakeNet()
    import sms.sources.http as http_mod
    monkeypatch.setattr(http_mod.httpx, "Client", net.client)
    monkeypatch.setattr(http_mod.time, "sleep", lambda seconds: None)      # rate limits are not what is under test
    return net


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch, request):
    """Any test that has not asked for the fake network fails if it opens a real connection."""
    if "fake_net" in request.fixturenames:
        return

    def refuse(self, *a, **k):
        raise AssertionError("test tried to use the real network")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
