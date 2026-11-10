"""Hard rule: no trading code, no trade subcommands, no signing, ever."""
import re
from pathlib import Path

import pytest

from sma import cli, http, safety
from sma.sources.gmgn import GMGN

SRC = Path(__file__).resolve().parents[1] / "src" / "sma"


def subcommands():
    p = cli.build_parser()
    sp = next(a for a in p._actions if a.__class__.__name__ == "_SubParsersAction")
    return set(sp.choices)


def test_cli_exposes_only_read_commands():
    cmds = subcommands()
    assert cmds == set(safety.ALLOWED_COMMANDS)
    assert not cmds & safety.FORBIDDEN_COMMAND_WORDS
    assert not any(re.search(r"buy|sell|swap|trade|order|snipe|sign|send|transfer", c) for c in cmds)


@pytest.mark.parametrize("word", sorted(safety.FORBIDDEN_COMMAND_WORDS))
def test_trade_subcommands_rejected(word):
    with pytest.raises(SystemExit):           # argparse rejects unknown subcommands
        cli.main([word])
    with pytest.raises(safety.TradingRefused):
        safety.check_command(word)


@pytest.mark.parametrize("url", [
    "https://lite-api.jup.ag/swap/v1/swap", "https://quote-api.jup.ag/v6/quote", "https://api.jup.ag/ultra/v1/order",
    "https://openapi.gmgn.ai/v1/trade/swap", "https://openapi.gmgn.ai/v1/user/wallet_holdings",
    "https://pumpportal.fun/api/trade-local", "https://x.y/v1/order",
])
def test_trade_urls_refused(url):
    with pytest.raises(safety.TradingRefused):
        http.request_json(url)


@pytest.mark.parametrize("method", ["sendTransaction", "eth_sendRawTransaction", "eth_sign", "eth_signTransaction"])
def test_signing_rpc_refused(method):
    with pytest.raises(safety.TradingRefused):
        http.post_json("https://api.mainnet-beta.solana.com", {"jsonrpc": "2.0", "id": 1, "method": method, "params": []})


def test_gmgn_whitelist_blocks_everything_else():
    g = GMGN("k")
    for path in ("/v1/trade/swap", "/v1/user/wallet_holdings", "/v1/cooking/create", "/v1/order/create"):
        with pytest.raises(safety.TradingRefused):
            g._call("POST", path)
    assert g.calls == 0


FORBIDDEN_CODE = re.compile(
    r"\bKeypair\b|from_secret_key|secret_key|nacl\.signing|eth_account|from web3|import web3|solders|"
    r"environ[^\n]*PRIVATE|environ[^\n]*MNEMONIC|environ[^\n]*SEED|sign_transaction|\.sign\(|"
    r"def (buy|sell|swap|place_order|trade)\b", re.I)


def test_no_trading_or_signing_code_in_source():
    hits = []
    for f in SRC.rglob("*.py"):
        if f.name == "safety.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN_CODE.search(line):
                hits.append(f"{f.name}:{i}: {line.strip()}")
    assert not hits, hits


def test_no_trading_dependencies():
    import tomllib
    proj = tomllib.loads((SRC.parents[1] / "pyproject.toml").read_text())["project"]
    deps = " ".join(proj["dependencies"] + sum(proj.get("optional-dependencies", {}).values(), [])).lower()
    for dep in ("solana", "solders", "web3", "eth-account", "anchorpy", "ccxt", "jupiter", "bip39", "mnemonic"):
        assert dep not in deps
