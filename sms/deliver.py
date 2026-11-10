"""Where alerts go: the console, a Telegram chat, a Discord channel. All optional; the website
reads the ledger instead. A channel that fails is logged and skipped — the alert is already on
the record by the time delivery starts.

The Telegram sender is reduced from cvxv666/fomo-robinhood-radar (MIT), fomo_agent/bot/telegram.py,
Copyright (c) 2026 fomo-agent contributors: plain Bot API over HTTP, a 429 is waited out once.
"""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)


class Console:
    name = "console"

    def __init__(self, out=print):
        self.out = out

    def send(self, alert: dict) -> bool:
        self.out("\n" + "─" * 64 + "\n" + alert["story"] + "\n" + "─" * 64)
        return True


class Telegram:
    name = "telegram"
    LIMIT = 4096

    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None, sleep=time.sleep):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.http = client or httpx.Client(timeout=20)
        self._sleep = sleep

    def send(self, alert: dict) -> bool:
        payload = {"chat_id": self.chat_id, "text": alert["story"][: self.LIMIT], "disable_web_page_preview": True}
        try:
            r = self.http.post(self.url, json=payload)
            if r.status_code == 429:
                wait = float((r.json().get("parameters") or {}).get("retry_after") or 3)
                self._sleep(min(wait, 30) + 0.05)
                r = self.http.post(self.url, json=payload)
            if r.status_code != 200:
                log.warning("telegram: HTTP %s — alert %s not delivered there", r.status_code, alert["id"])
                return False
            return True
        except (httpx.HTTPError, ValueError) as e:
            log.warning("telegram: %s — alert %s not delivered there", type(e).__name__, alert["id"])
            return False


class Discord:
    name = "discord"
    LIMIT = 2000

    def __init__(self, webhook_url: str, client: httpx.Client | None = None):
        self.url = webhook_url
        self.http = client or httpx.Client(timeout=20)

    def send(self, alert: dict) -> bool:
        text = alert["story"]
        if len(text) > self.LIMIT:
            text = text[: self.LIMIT - 1] + "…"
        try:
            r = self.http.post(self.url, json={"content": text, "allowed_mentions": {"parse": []}})
            if r.status_code >= 300:
                log.warning("discord: HTTP %s — alert %s not delivered there", r.status_code, alert["id"])
                return False
            return True
        except httpx.HTTPError as e:
            log.warning("discord: %s — alert %s not delivered there", type(e).__name__, alert["id"])
            return False


def from_settings(settings, console: bool = True) -> tuple:
    out = [Console()] if console else []
    if settings.telegram_bot_token and settings.telegram_chat_id:
        out.append(Telegram(settings.telegram_bot_token, settings.telegram_chat_id))
    if settings.discord_webhook_url:
        out.append(Discord(settings.discord_webhook_url))
    return tuple(out)
