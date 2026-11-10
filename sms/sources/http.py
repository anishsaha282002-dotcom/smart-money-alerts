"""One small HTTP client for every data source, with the two rules of this project built in.

1. Read-only. Any request whose path looks like trading, ordering, swapping, signing or token
   creation raises `TradingForbidden` before it leaves the machine. There is no flag to turn
   this off. tests/test_no_trading.py also runs the whole pipeline against this guard.
2. Fail soft. A source that is down, rate-limited or misconfigured returns None, is logged once
   per kind of failure, and the rest of the run carries on without it.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from ..ratelimit import RateLimiter

log = logging.getLogger(__name__)

# path fragments no data source needs and every execution API has
_FORBIDDEN = re.compile(
    r"/(trade|trades?/(swap|order)|swap|multi_swap|order|orders|strategy|cooking|create_token|"
    r"sign|sendtransaction|send_transaction|submit|execute|ultra|trigger|limit)(/|$)", re.I)
# ...except these read-only paths, which merely contain one of those words
_ALLOWED = re.compile(r"/pools/[^/]+/trades$", re.I)      # GeckoTerminal: a pool's public trade tape
# JSON-RPC methods that write to a chain
_FORBIDDEN_RPC = re.compile(r"^(sendTransaction|sendRawTransaction|eth_sendRawTransaction|eth_sendTransaction|"
                            r"eth_sign.*|personal_.*|simulateBundle|sendBundle)$")
POST_OK_HOSTS = ("openapi.gmgn.ai",)      # GMGN's read endpoints for call-outs are POST
# Read-only POSTs that are not trades: Helius Parsed Events (~10 credits) and
# public Solana JSON-RPC getters. Enhanced 100-credit history is not one of them.
_HELIUS_READ = ("mainnet.helius-rpc.com",)
_SOLANA_RPC_HOSTS = ("api.mainnet-beta.solana.com",)
_READ_RPC = re.compile(r"^get[A-Za-z0-9]+$")


class TradingForbidden(RuntimeError):
    """Raised instead of sending a request that could trade, sign or move funds."""


def check_readonly(method: str, url: str, json_body: dict | None = None) -> None:
    parts = urlsplit(url)
    path = parts.path
    if _FORBIDDEN.search(path) and not _ALLOWED.search(path):
        raise TradingForbidden(f"refusing {method} {parts.netloc}{path}: this tool is read-only and never trades")
    if method.upper() not in ("GET", "POST"):
        raise TradingForbidden(f"refusing {method} {parts.netloc}{path}: only reads are allowed")
    if method.upper() == "POST" and not _post_is_read(parts.netloc, path, json_body):
        raise TradingForbidden(f"refusing POST to {parts.netloc}{path}: data sources are read with GET")
    if isinstance(json_body, dict) and _FORBIDDEN_RPC.match(str(json_body.get("method", ""))):
        raise TradingForbidden(f"refusing RPC method {json_body['method']}: this tool never sends transactions")


def _post_is_read(host: str, path: str, json_body: dict | None) -> bool:
    if host in POST_OK_HOSTS:
        return True
    if host in _HELIUS_READ and (path.startswith("/v1/parsed-events/") or path.startswith("/v0/webhooks")):
        return True
    if host in _SOLANA_RPC_HOSTS:
        method = str((json_body or {}).get("method") or "")
        return bool(_READ_RPC.match(method)) and not method.lower().startswith("getsend")
    return False


class Http:
    def __init__(self, name: str, base: str = "", max_per_min: int = 30, headers: dict | None = None,
                 client: httpx.Client | None = None, timeout: float = 20.0, retries: int = 2,
                 sleep=None):
        self.name = name
        self.base = base.rstrip("/")
        self.http = client or httpx.Client(timeout=timeout, headers={"accept": "application/json",
                                                                     "user-agent": "smart-money-stories/0.1"})
        self.headers = headers or {}
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self.limiter = RateLimiter(max_per_min, name, sleep=self._sleep)
        self.retries = retries
        self.requests = 0
        self.failures = 0
        self.last_error = ""
        self._warned: set[str] = set()

    def _warn(self, kind: str, msg: str) -> None:
        self.failures += 1
        self.last_error = msg
        if kind not in self._warned:
            self._warned.add(kind)
            log.warning("%s: %s (this source is skipped; everything else keeps running)", self.name, msg)

    def request(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None,
                headers: dict | None = None):
        """Parsed JSON, or None if the source could not answer. Never raises for network trouble."""
        url = path if path.startswith("http") else f"{self.base}{path}"
        check_readonly(method, url, json_body)          # raises: a programming error, not an outage
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            self.requests += 1
            try:
                r = self.http.request(method, url, params=params, json=json_body,
                                      headers={**self.headers, **(headers or {})})
            except httpx.HTTPError as e:
                self._warn("network", f"network error ({type(e).__name__})")
                return None
            if r.status_code == 429 and attempt < self.retries:
                try:
                    wait = float(r.headers.get("retry-after") or 0)
                except ValueError:
                    wait = 0
                self._sleep(min(max(wait, 5 * (attempt + 1)), 30))
                continue
            if r.status_code >= 400:
                hint = {401: "key rejected", 403: "not allowed (key, plan or IP)", 404: "not found",
                        429: "rate limited"}.get(r.status_code, "error")
                self._warn(str(r.status_code), f"HTTP {r.status_code} {hint}{_reason(r)}")
                return None
            try:
                return r.json()
            except ValueError:
                self._warn("json", "answer was not JSON")
                return None
        return None

    def get(self, path: str, params: dict | None = None, headers: dict | None = None):
        return self.request("GET", path, params=params, headers=headers)


def _reason(r: httpx.Response) -> str:
    """The API's own short error code, when it sends one (e.g. GMGN's AUTH_IP_BLOCKED). Never the whole body."""
    try:
        body = r.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    code = body.get("error") or body.get("code") or body.get("message")
    return f": {str(code)[:60]}" if code else ""


def num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default
