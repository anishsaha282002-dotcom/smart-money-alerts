"""Optional, keyless safety checks: RugCheck for Solana, GoPlus for BNB Chain and Base.
The result is shown as warnings on the alert. It never hides an alert: a risky coin a good
wallet bought is still something that happened, and it stays on the record."""
from __future__ import annotations

from .http import Http, num

GOPLUS_CHAIN = {"bsc": "56", "base": "8453"}


def parse_rugcheck(body) -> dict | None:
    if not isinstance(body, dict):
        return None
    risks = [r.get("name") for r in body.get("risks") or [] if r.get("level") in ("danger", "warn") and r.get("name")]
    return {"source": "rugcheck", "risks": [str(r).lower() for r in risks][:5], "score": body.get("score_normalised")}


def parse_goplus(body, address: str) -> dict | None:
    result = (body or {}).get("result") or {}
    d = result.get(address.lower()) or result.get(address) or next(iter(result.values()), None)
    if not isinstance(d, dict):
        return None
    risks = []
    if d.get("is_honeypot") == "1":
        risks.append("flagged as a honeypot (may be unsellable)")
    if d.get("cannot_sell_all") == "1":
        risks.append("holders cannot sell their full balance")
    for side in ("buy_tax", "sell_tax"):
        tax = num(d.get(side))
        if tax is not None and tax > 0.10:
            risks.append(f"{side.replace('_', ' ')} {tax * 100:.0f}%")
    if d.get("is_open_source") == "0":
        risks.append("contract source is not verified")
    if d.get("is_mintable") == "1":
        risks.append("supply can be minted")
    if d.get("hidden_owner") == "1":
        risks.append("hidden owner")
    return {"source": "goplus", "risks": risks}


class Safety:
    name = "safety"

    def __init__(self, rugcheck: Http | None = None, goplus: Http | None = None):
        self.rugcheck = rugcheck or Http("rugcheck", "https://api.rugcheck.xyz", max_per_min=20)
        self.goplus = goplus or Http("goplus", "https://api.gopluslabs.io", max_per_min=20)

    def check(self, chain: str, address: str) -> dict | None:
        if chain == "solana":
            return parse_rugcheck(self.rugcheck.get(f"/v1/tokens/{address}/report/summary"))
        if chain in GOPLUS_CHAIN:
            return parse_goplus(self.goplus.get(f"/api/v1/token_security/{GOPLUS_CHAIN[chain]}",
                                                {"contract_addresses": address}), address)
        return None
