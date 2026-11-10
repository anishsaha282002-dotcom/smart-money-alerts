from __future__ import annotations

import copy
import os
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULTS = {
    "chains": ["solana", "bsc"],
    "paths": {"data_dir": "data", "ledger": "public/ledger.jsonl", "site_dir": "public",
              "wallets": "data/wallets.json", "callers": "data/callers.json", "helius_stream_db": ""},
    "alerts": {"min_wallet_grade": "B", "min_closed_trades": 3, "lookback_minutes": 60, "min_buy_usd": 300,
               "min_liquidity_usd": 10000, "max_mcap_usd": 100000000, "dedupe_hours": 24, "max_alerts_per_run": 10},
    "grading": {"window_days": 30, "shrink_k": 8, "low_sample": 5, "small_sample": 10,
                "closed_fraction": 0.9, "late_check_max_trades": 6},
    "discovery": {"gecko_trending_pools": 3, "fourmeme_pools": 2, "big_buy_usd": 1500,
                  "max_new_wallet_grades": 4, "solana_rpc_tx_budget": 60},
    "budgets": {"helius": 40, "gmgn": 20, "x": 10, "geckoterminal": 45},
    "ledger": {"horizons": ["15m", "1h", "4h", "24h"]},
    "narration": {"llm": False},
}
ENV_KEYS = ("HELIUS_API_KEY", "HELIUS_STREAM_DB", "GMGN_API_KEY", "X_BEARER_TOKEN", "SOLANA_RPC_URL", "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


def load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def _merge(a, b):
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
    return a


def load_config(path="config.yaml", root=None):
    root = Path(root or os.getcwd())
    load_dotenv(root / ".env")
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(path) if Path(path).is_absolute() else root / path
    if p.exists() and yaml:
        _merge(cfg, yaml.safe_load(p.read_text()) or {})
    cfg["root"] = str(root)
    cfg["env"] = {k: (os.environ.get(k) or "").strip() for k in ENV_KEYS}
    return cfg


def resolve(cfg, key):
    p = Path(cfg["paths"][key])
    return p if p.is_absolute() else Path(cfg["root"]) / p


HORIZON_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "24h": 86400}
GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1, "U": 0}
