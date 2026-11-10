"""Settings: secrets from the environment (.env), everything else from config.toml.

Nothing here is required. A missing key switches its source off and the rest keeps working.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is a dependency, but a missing .env must never be an error
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*a, **k):
        return False

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    # --- secrets, environment only
    helius_api_key: str = ""
    gmgn_api_key: str = ""
    x_bearer_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    anthropic_api_key: str = ""

    # --- general
    chains: tuple[str, ...] = ("solana", "bsc")
    data_dir: Path = ROOT / "data"
    web_dir: Path = ROOT / "web"

    # --- alerts
    min_grade: str = "B"
    min_buy_usd: float = 500.0
    cooldown_hours: float = 6.0
    cluster_window_min: int = 30
    lookback_days: int = 30
    max_alerts_per_run: int = 10

    # --- grading
    prior_trades: int = 10          # pseudo-trades at 50% the win rate is shrunk toward
    small_sample: int = 10          # fewer closed trades than this gets a warning
    cap_below: int = 5              # fewer than this can never grade above C

    # --- sources
    watch_wallets: dict[str, list[str]] = field(default_factory=dict)   # chain -> addresses
    keyless_pools_per_chain: int = 4
    gecko_max_per_min: int = 24
    helius_max_per_min: int = 60
    gmgn_max_per_min: int = 30
    jupiter_base: str = "https://lite-api.jup.ag"
    safety_checks: bool = True
    copy_history_buys: int = 6      # past buys per wallet priced for the copy check
    min_caller_followers: int = 2000

    # --- story
    llm_reword: bool = False
    llm_model: str = "claude-opus-5-5"

    def has(self, name: str) -> bool:
        return bool(getattr(self, name, ""))


_ENV = {
    "helius_api_key": "HELIUS_API_KEY",
    "gmgn_api_key": "GMGN_API_KEY",
    "x_bearer_token": "X_BEARER_TOKEN",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "discord_webhook_url": "DISCORD_WEBHOOK_URL",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}

_SECTIONS = ("general", "alerts", "grading", "sources", "story")


def load(config_path: str | Path | None = None, env_file: str | Path | None = None,
         environ: dict | None = None) -> Settings:
    """Build Settings. `environ` is for tests; by default the real environment (plus .env) is read."""
    if environ is None:
        load_dotenv(env_file or ROOT / ".env", override=False)
        environ = dict(os.environ)
    s = Settings()
    for attr, var in _ENV.items():
        setattr(s, attr, (environ.get(var) or "").strip())

    path = Path(config_path or environ.get("SMS_CONFIG") or ROOT / "config.toml")
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        for section in _SECTIONS:
            for k, v in (raw.get(section) or {}).items():
                if k in _ENV:            # secrets never come from the config file
                    continue
                if not hasattr(s, k):
                    raise ValueError(f"config.toml: unknown setting [{section}] {k}")
                if k in ("data_dir", "web_dir"):
                    v = Path(v) if Path(v).is_absolute() else ROOT / v
                elif k == "chains":
                    v = tuple(v)
                setattr(s, k, v)
        s.watch_wallets = {c: list(a) for c, a in (raw.get("wallets") or {}).items()}
    if environ.get("SMS_DATA_DIR"):
        s.data_dir = Path(environ["SMS_DATA_DIR"])
    if environ.get("SMS_WEB_DIR"):
        s.web_dir = Path(environ["SMS_WEB_DIR"])
    return s
