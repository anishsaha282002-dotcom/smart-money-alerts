"""Keyless Pump.fun trade listener: one `logsSubscribe` to the Pump.fun program on a public
Solana RPC websocket, decoded locally and matched against the wallet book.

Why: one subscription sees every bonding-curve trade, so the number of tracked wallets no longer
costs credits or subscriptions (30k wallets cost the same as 300). Pump.fun emits a TradeEvent
in its program logs ("Program data: <base64>") that carries mint, SOL amount, token amount,
side, trader and timestamp, so no per-trade getTransaction is needed.

Read-only: it subscribes to logs and never sends a transaction. The public RPC is not meant for
production and can rate-limit or drop the socket, so `listen` reconnects with a 60-90 s wait and
the caller keeps the Helius worker as the fallback. PumpSwap (graduated coins) emits pool-level
events without the mint; those are not decoded here yet.
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
import struct
import time

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUBLIC_WS = "wss://api.mainnet-beta.solana.com"
TRADE_EVENT = bytes.fromhex("bddb7fd34ee661ee")    # anchor discriminator of Pump.fun's TradeEvent
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_MIN_LEN = 8 + 32 + 8 + 8 + 1 + 32 + 8


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def decode_trade(raw: bytes) -> dict | None:
    """One TradeEvent payload -> dict, or None if it is not one."""
    if len(raw) < _MIN_LEN or raw[:8] != TRADE_EVENT:
        return None
    mint = b58encode(raw[8:40])
    sol, tokens = struct.unpack_from("<QQ", raw, 40)
    is_buy = raw[56] == 1
    user = b58encode(raw[57:89])
    (ts,) = struct.unpack_from("<q", raw, 89)
    return {"mint": mint, "sol": sol / 1e9, "token_amount": tokens / 1e6, "side": "buy" if is_buy else "sell",
            "wallet": user, "ts": ts}


def trades_from_logs(value: dict) -> list[dict]:
    """All Pump.fun trades in one logsNotification value (failed transactions skipped)."""
    if not isinstance(value, dict) or value.get("err"):
        return []
    out = []
    for line in value.get("logs") or []:
        if not line.startswith("Program data: "):
            continue
        try:
            raw = base64.b64decode(line[len("Program data: "):])
        except (ValueError, TypeError):
            continue
        t = decode_trade(raw)
        if t:
            t["signature"] = value.get("signature") or ""
            out.append(t)
    return out


def match(trades: list[dict], wallets: set[str]) -> list[dict]:
    return [t for t in trades if t["wallet"] in wallets]


def subscribe_payload(req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": "logsSubscribe",
            "params": [{"mentions": [PUMP_PROGRAM]}, {"commitment": "confirmed"}]}


async def listen(wallets: set[str], on_trade, stop: asyncio.Event, url: str = PUBLIC_WS,
                 silent_s: int = 120, log=print) -> None:     # pragma: no cover - needs a live socket
    """Run until `stop` is set. Calls on_trade(trade) for every tracked-wallet trade."""
    import websockets
    while not stop.is_set():
        try:
            async with websockets.connect(url, max_size=None, open_timeout=20, ping_interval=20,
                                          ping_timeout=20) as ws:
                await ws.send(json.dumps(subscribe_payload()))
                last = time.time()
                while not stop.is_set():
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                    except asyncio.TimeoutError:
                        if time.time() - last > silent_s:
                            log(f"pumpfun logs: silent {silent_s}s; reconnecting")
                            break
                        continue
                    val = ((msg.get("params") or {}).get("result") or {}).get("value")
                    if val is None:
                        continue
                    last = time.time()
                    for t in match(trades_from_logs(val), wallets):
                        on_trade(t)
        except Exception as e:  # noqa: BLE001 - a public socket fails in many ways; all mean "wait and retry"
            log(f"pumpfun logs: {type(e).__name__}; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=random.uniform(60, 90))
        except asyncio.TimeoutError:
            pass
