"""Public wallet book. Addresses and tags only — never a private key.

`data/smart_wallets.json` is a dated snapshot: 837 Solana wallets are streamed,
325 high-frequency or reserve Solana wallets are kept with stream=false, and
411 BSC wallets are stored the same way. Only stream=true wallets are polled
or subscribed. Bot, wash, bundle, and sniper tags stay on the record so the
grader can still refuse them.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT
from .models import norm

WALLETS_PATH = ROOT / "data" / "smart_wallets.json"
CHAIN = {"sol": "solana", "solana": "solana", "bsc": "bsc", "base": "base"}
# tags that the wallet grader already treats as a hard penalty
FLAG_TAGS = {
    "bot": "bot", "bot-like": "bot", "sybil": "bot",
    "wash": "wash", "wash-like": "wash",
    "sniper": "sniper", "bundle/sniper-like": "sniper",
    "bundle": "bundle", "bundler": "bundle",
}


def _chain(raw: str | None) -> str:
    return CHAIN.get((raw or "sol").lower(), (raw or "solana").lower())


def _row(raw: dict) -> dict | None:
    addr = (raw.get("address") or "").strip()
    if not addr or raw.get("enabled") is False:
        return None
    chain = _chain(raw.get("chain"))
    addr = norm(chain, addr)
    tags = [str(t).lower() for t in (raw.get("tags") or [])]
    for tag in list(tags):
        mapped = FLAG_TAGS.get(tag)
        if mapped and mapped not in tags:
            tags.append(mapped)
    narr = raw.get("narratives") or raw.get("narrative") or []
    if isinstance(narr, str):
        narr = [narr]
    try:
        score = float(raw.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "name": raw.get("name") or addr[:6],
        "chain": chain,
        "address": addr,
        "source": raw.get("source") or "",
        "tags": tags,
        "score": score,
        "stream": raw.get("stream") is not False,
        "narratives": [str(x) for x in narr if str(x).strip()] or ["general"],
        "vetting": raw.get("vetting") or {},
        "stats": raw.get("stats") or {},
        "enabled": True,
    }


def load_records(path: str | Path | None = None) -> tuple[list[dict], list[str]]:
    path = Path(path or WALLETS_PATH)
    if not path.is_file():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    notes = [str(n) for n in (data.get("notes") or [])]
    rows = []
    seen = set()
    blobs = list(data.get("wallets") or [])
    for key in ("bsc", "base", "solana"):
        extra = data.get(key)
        if isinstance(extra, list):
            blobs.extend(extra)
    for raw in blobs:
        if not isinstance(raw, dict):
            continue
        row = _row(raw)
        if not row:
            continue
        key = (row["chain"], row["address"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows, notes


def split_book(rows: list[dict]) -> dict[str, list[str]]:
    """Chain -> addresses that may be polled or streamed. Reserve stays out."""
    out: dict[str, list[str]] = {}
    for row in rows:
        if not row["stream"]:
            continue
        out.setdefault(row["chain"], []).append(row["address"])
    return out


def book_index(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["chain"], r["address"]): r for r in rows}


def stream_wallets(path: str | Path | None = None) -> dict:
    rows, notes = load_records(path)
    return {"notes": notes, "solana": [r for r in rows if r["chain"] == "solana"], "rows": rows}
