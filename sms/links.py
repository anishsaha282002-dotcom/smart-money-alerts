"""'Check it yourself' links on every alert, so nobody has to trust this tool's word for anything.
Read-only explorers and research pages only: never a trading or swap link."""
from __future__ import annotations

EXPLORER = {
    "solana": {"tx": "https://solscan.io/tx/{}", "account": "https://solscan.io/account/{}", "token": "https://solscan.io/token/{}"},
    "bsc": {"tx": "https://bscscan.com/tx/{}", "account": "https://bscscan.com/address/{}", "token": "https://bscscan.com/token/{}"},
    "base": {"tx": "https://basescan.org/tx/{}", "account": "https://basescan.org/address/{}", "token": "https://basescan.org/token/{}"},
}
BUBBLEMAPS = {"solana": "sol", "bsc": "bsc", "base": "base"}


def verify_links(alert: dict) -> list[dict]:
    chain = alert.get("chain", "solana")
    ex = EXPLORER.get(chain)
    if not ex:
        return []
    tok = (alert.get("token") or {}).get("address") or ""
    wallet = (alert.get("wallet") or {}).get("address") or ""
    tx = (alert.get("buy") or {}).get("tx") or ""
    out = []
    if tx and not tx.startswith("demo"):
        out.append({"label": "Buy transaction", "url": ex["tx"].format(tx)})
    if wallet:
        out.append({"label": "Wallet", "url": ex["account"].format(wallet)})
    if tok:
        out.append({"label": "Coin", "url": ex["token"].format(tok)})
        out.append({"label": "Chart", "url": f"https://dexscreener.com/{chain}/{tok}"})
        out.append({"label": "Holder map", "url": f"https://app.bubblemaps.io/{BUBBLEMAPS[chain]}/token/{tok}"})
        if chain == "solana":
            out.append({"label": "RugCheck", "url": f"https://rugcheck.xyz/tokens/{tok}"})
    return out
