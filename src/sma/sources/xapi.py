"""X API v2 recent search (X_BEARER_TOKEN), read-only. Pluggable: anything with a
``posts_about(symbol, address)`` method returning [{author, text, ts}] can replace it."""
from __future__ import annotations

import re

from .. import http
from ..util import parse_iso


class XRecentSearch:
    def __init__(self, bearer, budget=10):
        self.bearer, self.budget, self.calls, self.errors = bearer, budget, 0, []

    def posts_about(self, symbol, address):
        if self.calls >= self.budget:
            self.errors.append("budget reached")
            return None
        terms = [address]
        if symbol and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,11}", symbol):
            terms.append("$" + symbol)
        elif symbol and re.search(r"[\u4e00-\u9fff]", symbol):
            terms.append(symbol)
        self.calls += 1
        try:
            d = http.get_json("https://api.x.com/2/tweets/search/recent",
                              params={"query": f"({' OR '.join(terms)}) -is:retweet", "max_results": 100,
                                      "tweet.fields": "created_at,author_id", "expansions": "author_id",
                                      "user.fields": "username"},
                              headers={"Authorization": f"Bearer {self.bearer}"})
        except http.HttpError as e:
            self.errors.append(str(e)[:160])
            return None
        users = {u["id"]: u.get("username", "") for u in ((d or {}).get("includes") or {}).get("users", [])}
        return [{"author": users.get(t.get("author_id"), ""), "text": t.get("text", ""),
                 "ts": parse_iso(t["created_at"]) if t.get("created_at") else None} for t in (d or {}).get("data") or []]
