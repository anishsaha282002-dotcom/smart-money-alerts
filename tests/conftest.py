import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def fix():
    return lambda name: json.loads((FIX / name).read_text(encoding="utf-8"))


def mk_trade(token, side, ts, amount, value, unit="usd", wallet="W", chain="solana", price=None, created=None, tx=None):
    return {"chain": chain, "wallet": wallet, "token": token, "side": side, "ts": ts, "token_amount": amount, "value": value,
            "value_unit": unit, "price_usd": price, "tx": tx or f"{token}{side}{ts}", "source": "test", "token_created_ts": created}
