"""Runtime guard: this tool never trades.

Every outbound HTTP request goes through ``check_request``. It refuses anything that
looks like a swap, order, transaction submission or signing call, on any provider.
The CLI also exposes only read/report commands (see ``ALLOWED_COMMANDS``); a test
asserts that no trade-like subcommand exists or is ever invoked.
"""
from __future__ import annotations

import json
import re

ALLOWED_COMMANDS = frozenset({
    "run", "watch", "score-ledger", "report", "grade-wallet", "verify-ledger",
    "anchor", "demo", "sources",
})

FORBIDDEN_COMMAND_WORDS = frozenset({
    "buy", "sell", "swap", "trade", "order", "orders", "snipe", "copytrade", "copy-trade",
    "sign", "send", "transfer", "withdraw", "deposit", "wallet-create", "cook", "token-buy",
})

# URL fragments that belong to trading / signing APIs on the providers we touch
_FORBIDDEN_URL = re.compile(
    r"(/swap\b|/swap/|/order|/orders\b|/trade/|/v1/trade|quote-api\.jup|/ultra/|/execute\b|"
    r"/v1/user/wallet_holdings|/v1/cooking|/v1/token/create|transaction/send|/send-transaction|"
    r"lite-api\.jup\.ag/swap|api\.jup\.ag/swap|pumpportal\.fun/api/trade)",
    re.I,
)
_FORBIDDEN_RPC = frozenset({
    "sendTransaction", "sendRawTransaction", "eth_sendTransaction", "eth_sendRawTransaction",
    "eth_sign", "personal_sign", "eth_signTransaction", "eth_signTypedData", "eth_signTypedData_v4",
    "requestAirdrop", "simulateTransaction",
})


class TradingRefused(PermissionError):
    """Raised when something tries to reach a trading or signing endpoint."""


def check_request(url: str, body=None) -> None:
    if _FORBIDDEN_URL.search(url or ""):
        raise TradingRefused(f"refusing trade/sign endpoint: {url}")
    if body is None:
        return
    try:
        payload = body if isinstance(body, (dict, list)) else json.loads(body)
    except Exception:
        return
    items = payload if isinstance(payload, list) else [payload]
    for it in items:
        if isinstance(it, dict) and str(it.get("method", "")) in _FORBIDDEN_RPC:
            raise TradingRefused(f"refusing RPC method: {it.get('method')}")


def check_command(name: str) -> None:
    if name not in ALLOWED_COMMANDS or name in FORBIDDEN_COMMAND_WORDS:
        raise TradingRefused(f"command not allowed: {name}")
