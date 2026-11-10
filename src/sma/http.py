"""Tiny stdlib HTTP client with per-host pacing, retries, and the no-trading guard."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import safety

UA = "smart-money-alerts/0.1 (+https://github.com/; read-only research tool)"
# minimum seconds between calls per host (free-tier friendly)
PACE = {
    "api.geckoterminal.com": 2.1,      # ~30 req/min free
    "api.dexscreener.com": 0.25,
    "lite-api.jup.ag": 0.5,
    "api.coingecko.com": 2.5,
    "api.mainnet-beta.solana.com": 0.3,
    "mainnet.helius-rpc.com": 0.6,
    "openapi.gmgn.ai": 1.2,
    "api.x.com": 1.0,
    "api.twitter.com": 1.0,
}
_last: dict[str, float] = {}
_lock = threading.Lock()
CALL_LOG: list[tuple[str, str]] = []      # (method, url-without-query) - used by tests / `sma sources`


class HttpError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {str(body)[:200]}")
        self.code, self.body = code, body


def _pace(host: str):
    gap = PACE.get(host, 0.2)
    with _lock:
        wait = _last.get(host, 0) + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()


def request_json(url, *, method="GET", params=None, body=None, headers=None, timeout=25, tries=3):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}, doseq=True)
    safety.check_request(url, body)
    host = urllib.parse.urlparse(url).netloc
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    CALL_LOG.append((method, url.split("?")[0]))
    last = None
    for i in range(tries):
        _pace(host)
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace") if e.fp else ""
            last = HttpError(e.code, raw)
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = HttpError(0, repr(e))
            time.sleep(1.5 * (i + 1))
    raise last or HttpError(0, "unknown")


def get_json(url, **kw):
    return request_json(url, method="GET", **kw)


def post_json(url, body, **kw):
    return request_json(url, method="POST", body=body, **kw)
