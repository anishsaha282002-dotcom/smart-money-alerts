"""X (Twitter) API v2, optional (X_BEARER_TOKEN): who is posting about a coin, and how loud a
narrative is. Read-only search and counts.

Be aware: X's free tier does not include search. This source needs a paid tier; without one the
caller grade is built from GMGN call-outs instead, which are free.
"""
from __future__ import annotations

from datetime import datetime

from ..models import Call
from .http import Http

BASE = "https://api.x.com"


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def parse_search(body, chain: str, token: str) -> list[Call]:
    users = {u["id"]: u for u in ((body or {}).get("includes") or {}).get("users") or []}
    out = []
    for t in (body or {}).get("data") or []:
        u = users.get(t.get("author_id"), {})
        if not u.get("username") or not t.get("created_at"):
            continue
        out.append(Call(caller=u["username"], chain=chain, token=token, ts=_ts(t["created_at"]),
                        followers=(u.get("public_metrics") or {}).get("followers_count"), text=(t.get("text") or "")[:280]))
    return out


def parse_counts(body) -> tuple[int, int] | None:
    """(posts in the latest full hour, average posts per hour over the window)."""
    rows = (body or {}).get("data") or []
    if len(rows) < 3:
        return None
    counts = [r.get("tweet_count", 0) for r in rows]
    return counts[-2], round(sum(counts[:-1]) / len(counts[:-1]))


class XApi:
    name = "x"

    def __init__(self, bearer: str, http: Http | None = None):
        self.http = http or Http("x", BASE, max_per_min=10)
        self.headers = {"authorization": f"Bearer {bearer}"}

    def mentions(self, chain: str, token: str, symbol: str) -> list[Call]:
        ascii_sym = symbol.isascii() and symbol.isalnum()
        query = f'({"$" + symbol if ascii_sym else chr(34) + symbol + chr(34)} OR "{token}") -is:retweet'
        body = self.http.get("/2/tweets/search/recent", {
            "query": query, "max_results": 50, "tweet.fields": "created_at,author_id",
            "expansions": "author_id", "user.fields": "username,public_metrics"}, headers=self.headers)
        return parse_search(body, chain, token)

    def counts(self, query: str) -> tuple[int, int] | None:
        return parse_counts(self.http.get("/2/tweets/counts/recent", {"query": query, "granularity": "hour"},
                                          headers=self.headers))
