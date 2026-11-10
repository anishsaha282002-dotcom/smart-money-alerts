"""The hard rule of this project: it reads, it never trades.

Three layers are checked here:
  1. the HTTP guard refuses anything that looks like trading, signing or sending a transaction;
  2. the source code contains no signing / key-handling code and no wallet libraries;
  3. a complete live scan and a complete demo run are executed and every request they make is
     inspected — if any of them were a trade call, these tests fail.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import httpx
import pytest

from sms import config
from sms.ledger import Ledger
from sms.pipeline import Pipeline
from sms.scoring import score_calls, score_ledger
from sms.sources import gmgn
from sms.sources.http import Http, TradingForbidden, check_readonly
from sms.sources.hub import LiveHub
from sms.store import Store

ROOT = Path(__file__).resolve().parent.parent
TRADE_PATH = re.compile(r"trade|swap|order|strategy|cooking|sign|send|submit|execute|ultra|trigger", re.I)
READ_ONLY_EXCEPTION = re.compile(r"/pools/[^/]+/trades$")       # GeckoTerminal's public trade *tape*

FORBIDDEN_URLS = [
    "https://openapi.gmgn.ai/v1/trade/swap",
    "https://openapi.gmgn.ai/v1/trade/multi_swap",
    "https://openapi.gmgn.ai/v1/trade/strategy/create",
    "https://openapi.gmgn.ai/v1/trade/strategy/cancel",
    "https://openapi.gmgn.ai/v1/trade/quote",
    "https://openapi.gmgn.ai/v1/trade/query_order",
    "https://openapi.gmgn.ai/v1/cooking/create_token",
    "https://lite-api.jup.ag/swap/v1/quote",
    "https://lite-api.jup.ag/swap/v1/swap",
    "https://lite-api.jup.ag/ultra/v1/order",
    "https://lite-api.jup.ag/ultra/v1/execute",
    "https://lite-api.jup.ag/trigger/v1/createOrder",
    "https://api.example.com/v1/order",
    "https://api.example.com/v1/orders/123",
    "https://api.example.com/sign",
    "https://pumpportal.fun/api/trade",
]


@pytest.mark.parametrize("url", FORBIDDEN_URLS)
def test_guard_refuses_every_trade_like_url(url):
    for method in ("GET", "POST"):
        with pytest.raises(TradingForbidden):
            check_readonly(method, url)


def test_guard_refuses_writes_and_transaction_rpc():
    for method in ("PUT", "PATCH", "DELETE"):
        with pytest.raises(TradingForbidden):
            check_readonly(method, "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools")
    with pytest.raises(TradingForbidden):
        check_readonly("POST", "https://api.dexscreener.com/tokens/v1/solana/x")       # data is read with GET
    for rpc in ("sendTransaction", "sendRawTransaction", "eth_sendRawTransaction", "eth_signTypedData_v4", "personal_sign"):
        with pytest.raises(TradingForbidden):
            check_readonly("POST", "https://openapi.gmgn.ai/rpc", {"method": rpc})


def test_guard_allows_the_reads_we_do_make():
    check_readonly("GET", "https://api.geckoterminal.com/api/v2/networks/bsc/pools/0xabc/trades")
    check_readonly("GET", "https://api.helius.xyz/v0/addresses/abc/transactions")
    check_readonly("GET", "https://openapi.gmgn.ai/v1/user/smartmoney")
    check_readonly("POST", "https://openapi.gmgn.ai/v1/callout/global")


def test_http_client_raises_before_anything_is_sent():
    sent = []
    http = Http("t", "https://openapi.gmgn.ai", client=httpx.Client(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))))
    with pytest.raises(TradingForbidden):
        http.request("POST", "/v1/trade/swap", json_body={"amount": 1})
    assert sent == []


def test_gmgn_client_only_knows_read_routes():
    assert not set(gmgn.READ_ROUTES) & set(gmgn.WRITE_ROUTES)
    client = gmgn.Gmgn("k", http=Http("gmgn", gmgn.BASE, client=httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("a write route reached the network")))))
    for route in gmgn.WRITE_ROUTES:
        with pytest.raises((ValueError, TradingForbidden)):
            client._call("POST", route, body={})
    public = {n for n in dir(gmgn.Gmgn) if not n.startswith("_")}
    assert not {n for n in public if re.search(r"swap|trade|order|buy|sell|sign|create|cancel", n)}


# ------------------------------------------------------------- source scan

BANNED_IMPORTS = {"solders", "solana", "web3", "eth_account", "eth_keys", "bip_utils", "mnemonic", "nacl",
                  "base58", "ccxt", "jupiter_python_sdk", "anchorpy", "bitcoinlib", "ecdsa", "coincurve"}
BANNED_TEXT = re.compile(
    r"private[_ ]?key\s*=|secret[_ ]?key\s*=|seed[_ ]?phrase\s*=|mnemonic\s*=|\bKeypair\b|from_secret|"
    r"sign_transaction|signTransaction|send_raw_transaction|sendRawTransaction\(|\.sign\(|"
    r"PRIVATE_KEY|SECRET_KEY|WALLET_KEY|SEED_PHRASE|MNEMONIC", re.I)


def python_files():
    return sorted((ROOT / "sms").rglob("*.py"))


def test_no_wallet_or_signing_libraries_are_imported():
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in BANNED_IMPORTS, f"{path.name} imports {name}"


def test_no_key_handling_or_signing_code_in_the_package():
    guard = ROOT / "sms" / "sources" / "http.py"            # the guard itself has to name what it blocks
    for path in python_files():
        if path == guard:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            assert not BANNED_TEXT.search(code), f"{path.relative_to(ROOT)}:{n}: {line.strip()}"


def test_dependencies_and_env_template_hold_no_signing_material():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    listed = deps["dependencies"] + sum(deps["optional-dependencies"].values(), [])
    for dep in listed:
        assert re.split(r"[<>=\[ ]", dep)[0].lower().replace("-", "_") not in BANNED_IMPORTS
    env = (ROOT / ".env.example").read_text()
    names = re.findall(r"^([A-Z_]+)=", env, re.M)
    assert names and not [n for n in names if re.search(r"PRIVATE|SECRET|SEED|MNEMONIC|WALLET", n)]
    assert all(v == "" for v in re.findall(r"^[A-Z_]+=(.*)$", env, re.M)), ".env.example must hold no real values"
    assert set(names) == set(config._ENV.values())


# ------------------------------------------------ a whole scan, under watch

def assert_read_only(requests):
    assert requests, "the scan was expected to talk to its sources"
    for r in requests:
        path = r.url.path
        assert r.method in ("GET", "POST"), f"{r.method} {r.url}"
        if r.method == "POST":
            assert r.url.host == "openapi.gmgn.ai" and path in gmgn.READ_ROUTES, f"unexpected POST {r.url}"
        if TRADE_PATH.search(path):
            assert READ_ONLY_EXCEPTION.search(path), f"trade-like request: {r.method} {r.url}"
        assert path not in gmgn.WRITE_ROUTES


@pytest.mark.parametrize("keys", [{}, {"gmgn_api_key": "g", "helius_api_key": "h", "x_bearer_token": "x"}])
def test_full_live_scan_never_calls_a_trade_endpoint(fake_net, settings, keys):
    for k, v in keys.items():
        setattr(settings, k, v)
    settings.min_grade, settings.min_buy_usd = "D", 0
    settings.chains = ("solana", "bsc", "base")
    settings.watch_wallets = {"solana": ["WALLET_A"], "bsc": ["0xAbC0000000000000000000000000000000000001"]}
    store, ledger = Store(":memory:"), Ledger(settings.data_dir / "ledger.jsonl")
    clock = [1_794_284_000]
    hub = LiveHub(settings, store, clock=lambda: clock[0])
    pipe = Pipeline(hub, settings, store, ledger)
    store.put("cursor", 0, 0)
    alerts = pipe.run_once()
    clock[0] += 2 * 86400
    score_ledger(hub, ledger)
    score_calls(hub, store)
    pipe.grade("solana", "WALLET_A", refresh=True)
    assert alerts, "with every filter open the fixtures should produce at least one alert"
    assert_read_only(fake_net.requests)
    hosts = {r.url.host for r in fake_net.requests}
    assert "api.geckoterminal.com" in hosts
    if keys:
        assert {"openapi.gmgn.ai", "api.helius.xyz"} <= hosts


def test_demo_makes_no_network_calls_at_all(settings, monkeypatch):
    from sms import demo
    made = []
    monkeypatch.setattr(httpx.Client, "send", lambda self, request, **k: made.append(request) or pytest.fail("network used"))
    settings.min_grade, settings.chains = "C", ("solana", "bsc", "base")
    out = demo.run(settings, Ledger(settings.data_dir / "l.jsonl"), Store(":memory:"))
    assert out["alerts"] and made == []
