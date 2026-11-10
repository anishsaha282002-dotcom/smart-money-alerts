"""Delivery: console always; Telegram and Discord only when their env vars are set."""
from __future__ import annotations

from . import http


def deliver(text, env, *, enabled=True, log=print):
    sent = ["console"]
    log(text)
    log("-" * 72)
    if not enabled:
        return sent
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        try:
            http.post_json(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
                           {"chat_id": env["TELEGRAM_CHAT_ID"], "text": text[:4000], "disable_web_page_preview": True},
                           tries=2)
            sent.append("telegram")
        except Exception as e:  # never crash the run on delivery
            log(f"[telegram delivery failed: {str(e)[:120]}]")
    if env.get("DISCORD_WEBHOOK_URL"):
        try:
            http.post_json(env["DISCORD_WEBHOOK_URL"], {"content": text[:1990]}, tries=2)
            sent.append("discord")
        except Exception as e:
            log(f"[discord delivery failed: {str(e)[:120]}]")
    return sent
