"""Public Telegram channels, read from the web preview at https://t.me/s/<channel>.

Keyless and read-only: no bot token, no login, no joining. Only channels that publish a public
web preview can be read. Each post that names a contract address becomes a `Call` with the
caller set to "tg:<channel>". A call never creates an alert by itself; it is only shown next to
an alert that wallet activity already triggered, and graded like any other caller.
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime

from ..models import Call
from .http import Http

BASE = "https://t.me"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_POST = re.compile(r'data-post="([^"/]+)/(\d+)"(.*?)(?=data-post="|\Z)', re.S)
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
_SOL = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
_EVM = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_CHANNEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,63}$")


def b58_len(s: str) -> int | None:
    """Decoded byte length of a base58 string, or None if it is not base58."""
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    pad = len(s) - len(s.lstrip("1"))
    return pad + (n.bit_length() + 7) // 8


def is_solana_address(s: str) -> bool:
    return b58_len(s) == 32


def _clean(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(_html.unescape(text).split())


def parse_channel(page: str) -> list[dict]:
    """Posts on a t.me/s page: id, channel, ts, text, url. Posts without text are skipped."""
    out = []
    for m in _POST.finditer(page or ""):
        channel, pid, body = m.group(1), m.group(2), m.group(3)
        t, when = _TEXT.search(body), _TIME.search(body)
        if not t or not when:
            continue
        try:
            ts = int(datetime.fromisoformat(when.group(1).replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
        out.append({"channel": channel, "id": int(pid), "ts": ts, "text": _clean(t.group(1)),
                    "url": f"{BASE}/{channel}/{pid}"})
    return out


def addresses(text: str) -> list[tuple[str, str]]:
    """(chain, address) pairs named in a post. EVM addresses are reported as BNB Chain."""
    found = []
    for a in _EVM.findall(text or ""):
        found.append(("bsc", a.lower()))
    for a in _SOL.findall(_EVM.sub(" ", text or "")):
        if is_solana_address(a):
            found.append(("solana", a))
    seen, out = set(), []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def calls_from_posts(posts: list[dict]) -> list[Call]:
    out = []
    for p in posts:
        for chain, addr in addresses(p["text"]):
            out.append(Call(caller=f"tg:{p['channel']}", chain=chain, token=addr, ts=p["ts"], text=p["text"][:280]))
    return out


class TelegramPublic:
    name = "telegram"

    def __init__(self, channels: list[str] | tuple[str, ...], http: Http | None = None):
        self.channels = [c.lstrip("@") for c in channels if _CHANNEL.match(c.lstrip("@"))]
        self.http = http or Http("telegram", BASE, max_per_min=20)

    def posts(self, channel: str) -> list[dict]:
        page = self.http.get_text(f"/s/{channel}")
        return parse_channel(page or "")

    def calls(self) -> list[Call]:
        out = []
        for c in self.channels:
            out += calls_from_posts(self.posts(c))
        return out
