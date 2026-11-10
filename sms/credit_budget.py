"""Daily Helius credit budget for the read-only stream worker.

The Free plan is 1M credits/month. A large wallet list can exceed that if
hyperactive wallets are left subscribed, so the worker:
  * caps credits per America/Chicago day (default 30_000, ~900k/month)
  * logs daily usage
  * at >=80% of the daily cap, resubscribes to a top-ranked subset by score
  * pauses the stream at 100% until the next Chicago day
Never prints HELIUS_API_KEY. Never trades.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo('America/Chicago')
DEFAULT_DAILY_CAP = 30_000
DEFAULT_MONTHLY_CAP = 1_000_000
DEFAULT_SHRINK_SIZE = 150
SHRINK_RATIO = 0.80
MIN_SHRINK_SIZE = 25

NARRATIVE_KEYS = ('ai_agents', 'rwa_tokenization', 'war_geopolitics', 'major_figures', 'general')


def chicago_now():
    return datetime.now(CHICAGO)


def chicago_date(now=None):
    return (now or chicago_now()).strftime('%Y-%m-%d')


def seconds_until_next_chicago_midnight(now=None):
    now = now or chicago_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((nxt - now).total_seconds()))


def load_config(path_json=None):
    """Env vars win over smart_wallets.json credit_budget, which wins over defaults."""
    daily = DEFAULT_DAILY_CAP
    monthly = DEFAULT_MONTHLY_CAP
    shrink = DEFAULT_SHRINK_SIZE
    if path_json:
        try:
            import json
            with open(path_json) as f:
                j = json.load(f)
            cb = j.get('credit_budget') or {}
            if cb.get('daily_cap'):
                daily = int(cb['daily_cap'])
            if cb.get('monthly_cap') or cb.get('monthly_free_plan'):
                monthly = int(cb.get('monthly_cap') or cb['monthly_free_plan'])
            if cb.get('shrink_size'):
                shrink = int(cb['shrink_size'])
        except Exception:
            pass
    if os.environ.get('STREAM_DAILY_CREDIT_CAP'):
        daily = int(os.environ['STREAM_DAILY_CREDIT_CAP'])
    if os.environ.get('STREAM_MONTHLY_CREDIT_CAP'):
        monthly = int(os.environ['STREAM_MONTHLY_CREDIT_CAP'])
    if os.environ.get('STREAM_SHRINK_SIZE'):
        shrink = int(os.environ['STREAM_SHRINK_SIZE'])
    daily = max(100, int(daily))
    monthly = max(daily, int(monthly))
    shrink = max(MIN_SHRINK_SIZE, int(shrink))
    return {
        'daily_cap': daily,
        'monthly_cap': monthly,
        'shrink_size': shrink,
        'shrink_ratio': SHRINK_RATIO,
    }


def wallet_score(w):
    try:
        return float(w.get('score') or 0)
    except (TypeError, ValueError):
        return 0.0


def narratives_of(w):
    raw = w.get('narratives') or w.get('narrative') or []
    if isinstance(raw, str):
        raw = [raw]
    out = [str(x).strip().lower() or 'general' for x in raw if str(x).strip()]
    return out or ['general']


def diversify_top(wallets, n):
    """Take the top-n by score, keeping at least a few from each narrative when possible."""
    n = max(MIN_SHRINK_SIZE, int(n))
    ranked = sorted(wallets, key=wallet_score, reverse=True)
    if len(ranked) <= n:
        return list(ranked)
    per_narr = {}
    for w in ranked:
        for tag in narratives_of(w):
            per_narr.setdefault(tag, []).append(w)
    quota = max(3, n // max(4, len(per_narr) or 1))
    picked, seen = [], set()

    def add(w):
        addr = w.get('address')
        if not addr or addr in seen or len(picked) >= n:
            return
        seen.add(addr)
        picked.append(w)

    for tag in NARRATIVE_KEYS:
        for w in per_narr.get(tag, [])[:quota]:
            add(w)
    for w in ranked:
        add(w)
        if len(picked) >= n:
            break
    return picked


def select_active_wallets(wallets, shrink=False, shrink_size=DEFAULT_SHRINK_SIZE):
    cands = [w for w in (wallets or []) if w.get('stream', True) is not False
             and w.get('enabled', True) is not False]
    cands = [w for w in cands if (w.get('chain') or 'sol').lower() in ('sol', 'solana')]
    if shrink and len(cands) > shrink_size:
        return diversify_top(cands, shrink_size)
    return sorted(cands, key=wallet_score, reverse=True)


def observe(store, config, now=None):
    """Return daily usage and the action the worker should take: ok, shrink, or pause."""
    cap = int(config['daily_cap'])
    monthly_cap = int(config['monthly_cap'])
    cred = store.credits() if store is not None else {'day': 0, 'total': 0}
    day = int(cred.get('day') or 0)
    total = int(cred.get('total') or 0)
    action = 'ok'
    if day >= cap or total >= monthly_cap:
        action = 'pause'
    elif day >= int(cap * config['shrink_ratio']):
        action = 'shrink'
    return {
        'day': day,
        'day_date': cred.get('day_date') or chicago_date(now),
        'cap': cap,
        'monthly_total': total,
        'monthly_cap': monthly_cap,
        'ratio': (day / cap) if cap else 0,
        'action': action,
        'shrink_size': int(config['shrink_size']),
    }
