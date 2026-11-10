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


def parse_structure(body) -> dict | None:
    """Who holds the coin, from RugCheck's full report: top-10 share (pools excluded), insider
    wallets RugCheck's graph links together, and the creator's own share. Facts only."""
    if not isinstance(body, dict) or body.get("error"):
        return None
    known = body.get("knownAccounts") or {}
    pools = {a for a, v in known.items() if isinstance(v, dict) and str(v.get("type", "")).upper() == "AMM"}
    holders = [h for h in body.get("topHolders") or [] if isinstance(h, dict)]
    real = [h for h in holders if h.get("owner") not in pools and h.get("address") not in pools]
    top10 = round(sum(num(h.get("pct"), 0) for h in real[:10]), 1) if real else None
    insiders_top = sum(1 for h in real[:10] if h.get("insider"))
    supply = num((body.get("token") or {}).get("supply"))
    cbal = num(body.get("creatorBalance"))
    creator_pct = round(cbal / supply * 100, 2) if supply and cbal is not None else None
    nets = body.get("insiderNetworks") or []
    net_wallets = sum(int(num(n.get("size"), 0)) for n in nets if isinstance(n, dict))
    out = {"top10_pct": top10, "insiders_in_top10": insiders_top if real else None,
           "insiders_detected": body.get("graphInsidersDetected"), "insider_network_wallets": net_wallets or None,
           "creator_pct": creator_pct, "holders": body.get("totalHolders"), "rugged": bool(body.get("rugged"))}
    if all(v in (None, False) for v in out.values()):
        return None
    return out


def structure_notes(st: dict | None) -> list[str]:
    """Plain warnings from a structure read. Thresholds are display thresholds, not a verdict."""
    if not st:
        return []
    notes = []
    if st.get("rugged"):
        notes.append("RugCheck marks this token as rugged")
    if st.get("top10_pct") is not None and st["top10_pct"] >= 30:
        notes.append(f"top 10 holders (pools excluded) own {st['top10_pct']:.0f}%")
    if st.get("insiders_detected"):
        notes.append(f"{st['insiders_detected']} linked insider wallets detected by RugCheck")
    if st.get("creator_pct") is not None and st["creator_pct"] >= 5:
        notes.append(f"creator still holds {st['creator_pct']:.1f}%")
    return notes


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
            full = self.rugcheck.get(f"/v1/tokens/{address}/report")
            out = parse_rugcheck(full) if isinstance(full, dict) and not full.get("error") else None
            if out is None:
                return parse_rugcheck(self.rugcheck.get(f"/v1/tokens/{address}/report/summary"))
            out["structure"] = parse_structure(full)
            out["risks"] = (out["risks"] + structure_notes(out["structure"]))[:7]
            return out
        if chain in GOPLUS_CHAIN:
            return parse_goplus(self.goplus.get(f"/api/v1/token_security/{GOPLUS_CHAIN[chain]}",
                                                {"contract_addresses": address}), address)
        return None
