#!/usr/bin/env python3
"""Build smart_wallets.json from free public snapshots. Never invents addresses or stats."""
from __future__ import annotations

import json, math, re, collections, hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo('America/Chicago')
TODAY = datetime.now(CHICAGO).strftime('%Y-%m-%d')
HERE = Path(__file__).resolve().parent
SRC = Path('/tmp/wallets')
SOL_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
BSC_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

# Conservative narrative keywords applied only to public name/bio/notes text.
NARR_PAT = {
    'ai_agents': re.compile(
        r'\b(ai[- ]agents?|autonomous agents?|artificial intelligence|\bchatgpt\b|\bopenai\b|'
        r'\bgrok ai\b|\bllm[s]?\b|ai (?:bot|trader|caller)|agentic)\b', re.I),
    'rwa_tokenization': re.compile(
        r'\b(rwa[s]?|real[- ]world assets?|tokeni[sz]ation|tokeni[sz]ed (?:treasury|asset|equity|debt))\b', re.I),
    'war_geopolitics': re.compile(
        r'\b(geopolitics?|ukraine|gaza|world war|\biran war\b|military conflict)\b', re.I),
    'major_figures': re.compile(
        r'\b(elon musk|\belon\b|\bmusk\b|\btrump\b|donald trump|\btesla\b|\bspacex\b)\b', re.I),
}

# Extra full addresses published on Solana Trading blog posts (fetched 2026-11-09).
SOLANA_TRADING_EXTRA = [
    # https://solana-trading.com/blog/memecoin-trader-wallets-top10-2026
    {'name': 'Heyitsyolo', 'address': 'Av3xWHJ5EsoLZag6pr7LKbrGgLRTaykXomDD5kBhL9YQ',
     'source': 'https://solana-trading.com/blog/memecoin-trader-wallets-top10-2026',
     'stats_date': '2026-05', 'tags': ['smart', 'kol']},
    {'name': 'Clukz', 'address': 'G6fUXjMKPJzCY1rveAE6Qm7wy5U3vZgKDJmN1VPAdiZC',
     'source': 'https://solana-trading.com/blog/memecoin-trader-wallets-top10-2026',
     'stats_date': '2026-05', 'tags': ['smart', 'kol']},
    {'name': 'Cupsey', 'address': '2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f',
     'source': 'https://solana-trading.com/blog/memecoin-trader-wallets-top10-2026',
     'stats_date': '2026-05', 'tags': ['smart', 'kol']},
    {'name': 'Jijo', 'address': '4BdKaxN8G6ka4GYtQQWk4G4dZRUTX2vQH9GcXdBREFUk',
     'source': 'https://solana-trading.com/blog/memecoin-trader-wallets-top10-2026',
     'stats_date': '2026-05', 'tags': ['smart', 'kol']},
    # https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-july-2026-cented-pain-jimothy
    {'name': 'Pain', 'address': 'J6TDXvarvpBdPXTaTU8eJbtso1PUCYKGkVtMKUUY8iEa',
     'source': 'https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-july-2026-cented-pain-jimothy',
     'stats_date': '2026-07-31', 'tags': ['smart', 'kol'],
     'stats': {'winrate_30d': 0.44, 'pnl_30d_usd': 265937, 'stats_date': '2026-07-31'}},
    {'name': 'Kev', 'address': 'BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd',
     'source': 'https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-july-2026-cented-pain-jimothy',
     'stats_date': '2026-07-31', 'tags': ['smart', 'kol'],
     'stats': {'winrate_30d': 0.487, 'pnl_30d_usd': 139466, 'stats_date': '2026-07-31'}},
    # Casino from kolexplorer.com public leaderboard snippet fetched 2026-11-09
    {'name': 'Casino', 'address': '8rvAsDKeAcEjEkiZMug9k8v1y8mW6gQQiMobd89Uy7qR',
     'source': 'https://kolexplorer.com/',
     'stats_date': '2026-11-09', 'tags': ['smart', 'kol']},
]


def fnum(x, default=None):
    try:
        if x is None or x == '':
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def inum(x, default=0):
    v = fnum(x, None)
    return int(v) if v is not None else default


def recency_bonus(date_s):
    s = str(date_s or '')
    if s.startswith('2026-11'):
        return 35
    if s.startswith('2026-10'):
        return 28
    if s.startswith('2026-07') or s.startswith('2026-08') or s.startswith('2026-09'):
        return 20
    if s.startswith('2026-05') or s.startswith('2026-06'):
        return 15
    if s.startswith('2026-03') or s.startswith('2026-04'):
        return 6
    return 8


def tag_narratives(texts):
    blob = ' '.join(t for t in texts if t)
    found = [k for k, pat in NARR_PAT.items() if pat.search(blob)]
    return found or ['general']


def merge(dst, src):
    """Merge a newly seen record into dst (in place). Never overwrite a stat with None."""
    for k in ('name', 'source', 'stats_date'):
        if src.get(k) and (not dst.get(k) or dst.get(k) in (dst.get('address', '')[:6], '')):
            if k == 'name' and src['name'] and len(src['name']) > len(str(dst.get('name') or '')):
                dst['name'] = src['name']
            elif k != 'name':
                dst[k] = src[k]
    if src.get('name') and (not dst.get('name') or dst['name'] == dst['address'][:6]):
        dst['name'] = src['name']
    # keep the most recent source as primary if newer
    if recency_bonus(src.get('stats_date')) > recency_bonus(dst.get('stats_date')) and src.get('source'):
        dst['source'] = src['source']
        dst['stats_date'] = src['stats_date']
    dst.setdefault('sources', [])
    if src.get('source') and src['source'] not in dst['sources']:
        dst['sources'].append(src['source'])
    for t in src.get('tags') or []:
        if t not in dst['tags']:
            dst['tags'].append(t)
    st = dst.setdefault('stats', {})
    for k, v in (src.get('stats') or {}).items():
        if v is not None and st.get(k) is None:
            st[k] = v
        elif k.endswith('_date') and recency_bonus(v) > recency_bonus(st.get(k)):
            st[k] = v
        elif k in ('txs_1d', 'txs_7d', 'txs_30d', 'wins', 'losses') and inum(v) and inum(v) >= inum(st.get(k)):
            # prefer the record that has counts; if both, keep already set unless we also update date
            pass
    # If src stats_date is newer, prefer its numeric stats
    if recency_bonus(src.get('stats_date')) >= recency_bonus(st.get('stats_date') or dst.get('stats_date')):
        for k, v in (src.get('stats') or {}).items():
            if v is not None:
                st[k] = v
    dst.setdefault('texts', [])
    for t in src.get('texts') or []:
        if t and t not in dst['texts']:
            dst['texts'].append(t)
    return dst


def new_rec(addr, chain='sol', **kw):
    return {
        'address': addr,
        'chain': chain,
        'name': kw.get('name') or addr[:6],
        'source': kw.get('source') or '',
        'sources': [kw['source']] if kw.get('source') else [],
        'tags': list(kw.get('tags') or []),
        'stats': dict(kw.get('stats') or {}),
        'stats_date': kw.get('stats_date') or (kw.get('stats') or {}).get('stats_date'),
        'texts': list(kw.get('texts') or []),
        'gmgn_tags': list(kw.get('gmgn_tags') or []),
    }


def add(bucket, addr, chain='sol', **kw):
    addr = (addr or '').strip()
    if chain == 'sol' and not SOL_RE.match(addr):
        return
    if chain == 'bsc' and not BSC_RE.match(addr):
        return
    if addr not in bucket:
        bucket[addr] = new_rec(addr, chain, **kw)
    else:
        merge(bucket[addr], {'address': addr, **kw})
    if kw.get('gmgn_tag'):
        if kw['gmgn_tag'] not in bucket[addr]['gmgn_tags']:
            bucket[addr]['gmgn_tags'].append(kw['gmgn_tag'])


def gmgn_stats(it, date='2026-03-09'):
    wr = fnum(it.get('winrate_30d'))
    return {
        'winrate_1d': fnum(it.get('winrate_1d')),
        'winrate_7d': fnum(it.get('winrate_7d')),
        'winrate_30d': wr,
        'pnl_1d_usd': fnum(it.get('realized_profit_1d')),
        'pnl_7d_usd': fnum(it.get('realized_profit_7d')),
        'pnl_30d_usd': fnum(it.get('realized_profit_30d')),
        'txs_1d': inum(it.get('txs_1d')),
        'txs_7d': inum(it.get('txs_7d')),
        'txs_30d': inum(it.get('txs_30d') or it.get('txs')),
        'buy_30d': inum(it.get('buy_30d')),
        'sell_30d': inum(it.get('sell_30d')),
        'avg_hold_s_30d': fnum(it.get('avg_holding_period_30d')),
        'follow_count': inum(it.get('follow_count')),
        'stats_date': date,
        'stats_source': 'https://github.com/nirholas/kol-quest/blob/main/solwallets.json',
    }


def texts_from_gmgn(it):
    return [it.get('name'), it.get('nickname'), it.get('twitter_name'),
            it.get('twitter_username'), it.get('twitter_description')]


def load_gmgn_sol(bucket):
    data = json.loads((SRC / 'solwallets.json').read_text())
    date = (data.get('meta') or {}).get('startedAt', '2026-03-09')[:10]
    src = 'https://github.com/nirholas/kol-quest/blob/main/solwallets.json'
    # ranked quality lists
    for tag, lst in (data.get('smartMoney') or {}).get('wallets', {}).items():
        for it in lst or []:
            addr = (it.get('wallet_address') or it.get('address') or '').strip()
            tags = ['smart']
            if tag in ('smart_degen', 'launchpad_smart', 'live'):
                tags.append(tag)
            elif tag in ('snipe_bot',):
                tags.append('sniper')
            elif tag == 'fresh_wallet':
                tags.append('fresh')
            elif tag == 'top_dev':
                tags.append('top_dev')
            add(bucket, addr, name=it.get('name') or it.get('nickname') or it.get('twitter_username'),
                source=src, stats_date=date, tags=tags, stats=gmgn_stats(it, date),
                texts=texts_from_gmgn(it), gmgn_tag=tag)
    for it in data.get('kol', {}).get('wallets') or []:
        addr = (it.get('wallet_address') or it.get('address') or '').strip()
        add(bucket, addr, name=it.get('name') or it.get('nickname') or it.get('twitter_username'),
            source=src, stats_date=date, tags=['smart', 'kol'], stats=gmgn_stats(it, date),
            texts=texts_from_gmgn(it), gmgn_tag='kol')
    for key, tag in (('walletsBySmartMoney', 'smart_degen'), ('walletsByLaunchpad', 'launchpad_smart'),
                     ('walletsByKOL', 'kol'), ('walletsByLive', 'live'),
                     ('walletsByFreshWallet', 'fresh'), ('walletsBySniper', 'sniper'),
                     ('walletsByTopDev', 'top_dev'), ('walletsAll', 'gmgn_all')):
        for it in (data.get('interceptorRaw') or {}).get(key) or []:
            if not isinstance(it, dict):
                continue
            addr = (it.get('wallet_address') or it.get('address') or '').strip()
            tags = ['smart']
            if tag == 'kol':
                tags.append('kol')
            else:
                tags.append(tag)
            st = gmgn_stats(it, date) if 'txs_30d' in it or 'winrate_30d' in it or 'realized_profit_30d' in it else {'stats_date': date}
            add(bucket, addr, name=it.get('name') or it.get('nickname') or it.get('twitter_username'),
                source=src, stats_date=date, tags=tags, stats=st, texts=texts_from_gmgn(it), gmgn_tag=tag)
    return date


def load_gmgn_bsc(bucket):
    data = json.loads((SRC / 'bscwallets.json').read_text())
    date = (data.get('meta') or {}).get('startedAt', '2026-03-09')[:10]
    src = 'https://github.com/nirholas/kol-quest/blob/main/bscwallets.json'
    for key, tag in (('walletsBySmartMoney', 'smart_degen'), ('walletsByLaunchpad', 'launchpad_smart'),
                     ('walletsByKOL', 'kol'), ('walletsByLive', 'live'),
                     ('walletsByFreshWallet', 'fresh'), ('walletsBySniper', 'sniper'),
                     ('walletsAll', 'gmgn_all')):
        for it in (data.get('interceptorRaw') or {}).get(key) or []:
            if not isinstance(it, dict):
                continue
            addr = (it.get('wallet_address') or it.get('address') or '').strip()
            tags = ['smart']
            tags.append('kol' if tag == 'kol' else tag)
            st = gmgn_stats(it, date) if 'winrate_30d' in it or 'txs_30d' in it else {'stats_date': date}
            add(bucket, addr, chain='bsc', name=it.get('name') or it.get('nickname') or it.get('twitter_username'),
                source=src, stats_date=date, tags=tags, stats=st, texts=texts_from_gmgn(it), gmgn_tag=tag)
    for it in data.get('kol', {}).get('wallets') or []:
        addr = (it.get('wallet_address') or it.get('address') or '').strip()
        add(bucket, addr, chain='bsc', name=it.get('name') or it.get('nickname'),
            source=src, stats_date=date, tags=['smart', 'kol'], stats=gmgn_stats(it, date),
            texts=texts_from_gmgn(it), gmgn_tag='kol')
    return date


def load_kolscan(bucket):
    src = 'https://github.com/nirholas/kol-quest/blob/main/site/data/kolscan-leaderboard.json'
    rows = json.loads((SRC / 'kolscan-leaderboard.json').read_text())
    # unknown scrape date; file is the committed public snapshot
    date = '2026-11-09'  # retrieved today; underlying scrape date not published
    by = collections.defaultdict(dict)
    for it in rows:
        addr = (it.get('wallet_address') or it.get('wallet') or '').strip()
        tf = str(it.get('timeframe') or '')
        by[addr][tf] = it
    for addr, tfs in by.items():
        m = tfs.get('30') or tfs.get(30) or {}
        w = tfs.get('7') or {}
        d = tfs.get('1') or {}
        pick = m or w or d
        wins, losses = inum(pick.get('wins')), inum(pick.get('losses'))
        wr = (wins / (wins + losses)) if (wins + losses) else None
        st = {
            'pnl_30d_sol': fnum(m.get('profit')) if m else None,
            'pnl_7d_sol': fnum(w.get('profit')) if w else None,
            'pnl_1d_sol': fnum(d.get('profit')) if d else None,
            'wins': wins, 'losses': losses, 'winrate_30d': wr if m else None,
            'trades': wins + losses,
            'stats_date': date,
            'stats_source': src,
        }
        name = pick.get('name')
        texts = [name, pick.get('twitter')]
        add(bucket, addr, name=name, source=src, stats_date=date,
            tags=['smart', 'kol'], stats=st, texts=texts)
    return len(by)


def load_frozen(bucket):
    src = 'https://evidencedeflator.com/data/kolscan/frozen-2026-10-15.json'
    data = json.loads(Path('/tmp/wallets/frozen-2026-10-15.json').read_text()) if (SRC / 'frozen-2026-10-15.json').exists() else None
    if data is None:
        # already fetched via WebFetch earlier into this process? write from members if file missing
        return 0
    date = data.get('frozen_at') or '2026-10-15'
    n = 0
    for it in data.get('members') or []:
        addr = (it.get('wallet') or it.get('wallet_address') or '').strip()
        wins, losses = inum(it.get('wins')), inum(it.get('losses'))
        wr = (wins / (wins + losses)) if (wins + losses) else None
        add(bucket, addr, name=it.get('name'), source=src, stats_date=date, tags=['smart', 'kol'],
            stats={'pnl_30d_sol': fnum(it.get('profit_sol_30d')), 'wins': wins, 'losses': losses,
                   'winrate_30d': wr, 'trades': wins + losses, 'stats_date': date, 'stats_source': src},
            texts=[it.get('name')])
        n += 1
    for it in data.get('all_boards') or []:
        addr = (it.get('wallet_address') or it.get('wallet') or '').strip()
        add(bucket, addr, name=it.get('name'), source=src, stats_date=date, tags=['smart', 'kol'],
            texts=[it.get('name'), it.get('twitter')])
        n += 1
    return n


def load_verified(bucket):
    data = json.loads((SRC / 'verified.json').read_text())
    src_note = 'https://github.com/duolaAmengweb3/solana-alpha-tracker/blob/main/packages/core/src/data/verified.json'
    date = data.get('version') or '2026-05-03'
    for it in data.get('kols') or []:
        addr = (it.get('wallet') or it.get('address') or '').strip()
        add(bucket, addr, name=it.get('handle') or it.get('name'),
            source=it.get('source_url') or src_note, stats_date=date,
            tags=['smart', 'kol', 'verified'], texts=[it.get('handle'), it.get('notes')],
            stats={'stats_date': date, 'stats_source': it.get('source_url') or src_note})
    return len(data.get('kols') or [])


def load_yksanjo(bucket):
    data = json.loads((SRC / 'yksanjo-2026-05-21.json').read_text())
    date = (data.get('fetched_at') or '2026-05-21')[:10]
    src = 'https://github.com/yksanjo/kol-tracker/blob/main/snapshots/2026-05-21_0320Z.json'
    n = 0
    for key, pnl_key in (('monthly', 'pnl_30d_sol'), ('weekly', 'pnl_7d_sol'), ('daily', 'pnl_1d_sol')):
        for it in data.get(key) or []:
            addr = (it.get('wallet') or '').strip()
            wins, losses = inum(it.get('wins')), inum(it.get('losses'))
            wr = (wins / (wins + losses)) if (wins + losses) else None
            st = {pnl_key: fnum(it.get('profit_sol')), 'wins': wins, 'losses': losses,
                  'trades': wins + losses, 'stats_date': date, 'stats_source': src}
            if key == 'monthly':
                st['winrate_30d'] = wr
            add(bucket, addr, name=it.get('name'), source=src, stats_date=date,
                tags=['smart', 'kol'], stats=st, texts=[it.get('name'), it.get('twitter')])
            n += 1
    return n


def load_existing(bucket):
    cur = json.loads((HERE / 'smart_wallets.json').read_text())
    for w in cur.get('wallets') or []:
        add(bucket, w.get('address'), name=w.get('name'), source=w.get('source'),
            stats_date='2026-11-01', tags=w.get('tags') or ['smart'],
            texts=[w.get('name')])
        if w.get('source_also'):
            bucket[w['address']]['sources'].append(w['source_also'])


def load_solana_trading_extra(bucket):
    for it in SOLANA_TRADING_EXTRA:
        add(bucket, it['address'], name=it['name'], source=it['source'],
            stats_date=it.get('stats_date'), tags=it.get('tags') or ['smart', 'kol'],
            stats=it.get('stats') or {'stats_date': it.get('stats_date')},
            texts=[it['name']])


def classify(rec):
    tags = set(t.lower() for t in rec.get('tags') or [])
    gm = set(t.lower() for t in rec.get('gmgn_tags') or [])
    st = rec.get('stats') or {}
    txs_1d = inum(st.get('txs_1d'))
    txs_7d = inum(st.get('txs_7d'))
    txs_30d = inum(st.get('txs_30d') or st.get('trades'))
    wins, losses = inum(st.get('wins')), inum(st.get('losses'))
    trades = txs_30d or (wins + losses)
    wr = fnum(st.get('winrate_30d'))
    pnl = fnum(st.get('pnl_30d_usd'))
    pnl_sol = fnum(st.get('pnl_30d_sol'))
    daily = txs_1d
    if not daily and txs_7d:
        daily = txs_7d / 7.0
    elif not daily and trades:
        # only a 30d total — rough
        daily = trades / 30.0
    rec['_daily'] = daily
    rec['_trades'] = trades
    rec['_wr'] = wr
    rec['_pnl'] = pnl
    rec['_pnl_sol'] = pnl_sol

    is_snipe = ('sniper' in tags or 'snipe_bot' in gm or 'walletsbysniper' in gm)
    is_dev = ('top_dev' in tags or 'walletsbytopdev' in gm) and not ({'kol', 'smart_degen', 'launchpad_smart', 'live'} & (tags | gm))
    only_fresh = (('fresh' in tags or 'fresh_wallet' in gm or 'walletsbyfreshwallet' in gm)
                  and not ({'kol', 'smart_degen', 'launchpad_smart', 'live', 'verified'} & (tags | gm | set())))
    if 'kol' in tags:
        only_fresh = False
    no_activity = trades == 0 and not pnl and not pnl_sol and not wr
    extreme_hf = daily >= 1000 or txs_1d >= 1000 or (txs_7d / 7.0 if txs_7d else 0) >= 1000
    high_freq = daily >= 200 or txs_1d >= 200 or (txs_7d / 7.0 if txs_7d else 0) >= 200
    one_off = trades <= 2 and daily < 5 and 'verified' not in tags and 'kol' not in tags

    rec['_flags'] = {
        'snipe': is_snipe and 'kol' not in tags,
        'dev_only': is_dev,
        'fresh_only': only_fresh,
        'no_activity': no_activity,
        'extreme_hf': extreme_hf,
        'high_freq': high_freq and not extreme_hf,
        'one_off': one_off,
    }
    return rec


def quality_ok_stream(rec):
    f = rec['_flags']
    if f['snipe'] or f['dev_only'] or f['no_activity'] or f['extreme_hf'] or f['high_freq'] or f['one_off']:
        return False
    if f['fresh_only']:
        # higher bar: need a real published track record
        st = rec['stats']
        wr = rec['_wr']
        pnl = rec['_pnl'] or 0
        if rec['_trades'] < 20 or wr is None or wr < 0.40 or pnl <= 1000:
            return False
    # need some evidence of trading
    if rec['_trades'] < 10 and 'kol' not in rec['tags'] and 'verified' not in rec['tags']:
        return False
    # if winrate known and very low with lots of trades and no profit, skip
    if rec['_wr'] is not None and rec['_wr'] < 0.20 and rec['_trades'] >= 30 and not (rec['_pnl'] and rec['_pnl'] > 0) and not (rec['_pnl_sol'] and rec['_pnl_sol'] > 0):
        return False
    return True


def quality_ok_reserve(rec):
    f = rec['_flags']
    if f['snipe'] or f['dev_only'] or f['no_activity'] or f['one_off']:
        return False
    # high-freq and extreme-hf go to reserve (tagged), not stream
    if f['extreme_hf'] or f['high_freq']:
        return True
    # leftover quality that missed stream bar (e.g. thin fresh)
    if rec['_trades'] >= 10 or 'kol' in rec['tags'] or 'verified' in rec['tags']:
        return True
    return False


def score_rec(rec):
    s = recency_bonus(rec.get('stats_date'))
    tags = rec['tags']
    if 'kol' in tags:
        s += 20
    if 'verified' in tags:
        s += 15
    if rec.get('name') and rec['name'] != rec['address'][:6] and not rec['name'].startswith('0x'):
        s += 8
    wr = rec['_wr']
    if wr is not None:
        s += wr * 25
    pnl = rec['_pnl'] or ((rec['_pnl_sol'] or 0) * 85)  # rough SOL->USD only for ranking, not published
    if pnl and pnl > 0:
        s += min(15, math.log10(pnl + 1) * 4)
    if rec['_trades'] >= 20:
        s += 5
    if rec['_flags']['high_freq'] or rec['_flags']['extreme_hf']:
        s -= 30
    if rec['_flags']['fresh_only']:
        s -= 8
    narr = tag_narratives(rec.get('texts') or [rec.get('name')])
    rec['narratives'] = narr
    if narr != ['general']:
        s += 5
    rec['score'] = round(s, 2)
    return rec


def emit_wallet(rec, stream, extra_tags=None):
    tags = list(rec['tags'])
    for t in extra_tags or []:
        if t not in tags:
            tags.append(t)
    if rec['_flags']['high_freq'] and 'high_frequency' not in tags:
        tags.append('high_frequency')
    if rec['_flags']['extreme_hf'] and 'high_frequency' not in tags:
        tags.append('high_frequency')
    st = rec.get('stats') or {}
    # only publish stats that were actually present
    stats = {k: v for k, v in st.items() if v is not None}
    stats.setdefault('stats_date', rec.get('stats_date'))
    out = {
        'name': rec.get('name') or rec['address'][:6],
        'chain': rec.get('chain') or 'sol',
        'address': rec['address'],
        'source': rec.get('source') or (rec.get('sources') or ['unspecified'])[0],
        'enabled': True,
        'stream': bool(stream),
        'tags': tags,
        'narratives': rec.get('narratives') or ['general'],
        'score': rec.get('score') or 0,
        'stats': stats,
        'vetting': rec.get('vetting') or {
            'depth': 'public_stats',
            'credits': 0,
            'date': TODAY,
            'note': 'classified from published leaderboard stats only',
        },
    }
    if rec.get('sources') and len(rec['sources']) > 1:
        out['source_also'] = rec['sources'][1]
    return out


def main():
    sol, bsc = {}, {}
    load_existing(sol)
    load_solana_trading_extra(sol)
    gmgn_date = load_gmgn_sol(sol)
    bsc_date = load_gmgn_bsc(bsc)
    n_ks = load_kolscan(sol)
    # frozen file: save if we can from earlier fetch path
    frozen_path = SRC / 'frozen-2026-10-15.json'
    n_fr = load_frozen(sol) if frozen_path.exists() else 0
    n_ver = load_verified(sol)
    n_yk = load_yksanjo(sol)

    for rec in sol.values():
        classify(rec)
        score_rec(rec)

    stream, reserve, rejected = [], [], collections.Counter()
    for rec in sol.values():
        f = rec['_flags']
        if quality_ok_stream(rec):
            stream.append(rec)
        elif quality_ok_reserve(rec):
            reserve.append(rec)
        else:
            if f['snipe']:
                rejected['snipe'] += 1
            elif f['dev_only']:
                rejected['dev_only'] += 1
            elif f['no_activity']:
                rejected['no_activity'] += 1
            elif f['one_off']:
                rejected['one_off'] += 1
            else:
                rejected['other'] += 1

    stream.sort(key=lambda r: -r['score'])
    reserve.sort(key=lambda r: -r['score'])

    # BSC quality (not streamed)
    bsc_out = []
    for rec in bsc.values():
        classify(rec)
        score_rec(rec)
        f = rec['_flags']
        if f['snipe'] or f['no_activity'] or f['one_off']:
            continue
        if rec['_trades'] < 10 and 'kol' not in rec['tags']:
            continue
        bsc_out.append(emit_wallet(rec, stream=False))
    bsc_out.sort(key=lambda w: -w['score'])

    # counts by narrative (streamed)
    narr_counts = collections.Counter()
    for rec in stream:
        for n in rec.get('narratives') or ['general']:
            narr_counts[n] += 1

    notes = [
        'Public snapshot compiled 2026-11-09 (America/Chicago). Addresses and stats are copied from free public pages and committed GitHub data files. Stats are NOT live; dates are attached on each wallet. This is not financial advice.',
        'Primary Solana sources: existing 10 wallets from https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-october-2026 (KOL Explorer 1 Nov 2026 reading); additional Solana Trading posts (May/July 2026); nirholas/kol-quest solwallets.json (GMGN scrape started 2026-03-09) and site/data/kolscan-leaderboard.json (retrieved 2026-11-09, underlying scrape date not published); evidencedeflator kolscan freeze 2026-10-15 if present; duolaAmengweb3/solana-alpha-tracker verified.json (2026-05-03); yksanjo/kol-tracker snapshot 2026-05-21.',
        'BSC wallets (not watched by the Helius Solana stream) come from nirholas/kol-quest bscwallets.json (GMGN scrape 2026-03-09) and are for the GeckoTerminal/BSC path or later use.',
        'Blocked or unusable on 2026-11-09 without credentials: gmgn.ai live rank endpoints (HTTP 403/Cloudflare); Cielo wallet-discovery and list pages (no full addresses in fetchable HTML, and Wallet Discovery is a paid feature); kolscan.io/api/leaderboard (HTTP 400 on unauthenticated GET). MemeGram (https://memegram.space/) publishes Telegram caller performance, not wallet addresses — those callers are stored separately in callers.json under telegram_callers.',
        'Filters: dropped sniper-only, top-dev-only, zero-activity, and 1-2 trade one-offs from both lists. Wallets at or above ~200 published swaps/day are tagged high_frequency and kept in the file with stream=false (reserve) so they do not burn Free-plan credits. The stream worker also enforces a daily credit cap (default 30,000) and will shrink to the top-ranked subset at 80% of that cap.',
        'tags: every streamed wallet is smart (counts toward the 2-in-1h cluster). kol is set for Kolscan / verified / named-KOL sources and feeds the KOL-buy label. narratives are tagged only when public name/bio/notes text matches conservative keywords; most wallets are general memecoin traders.',
        'Someone cloning this repo only needs HELIUS_API_KEY (free, no card) to run the stream. Do not commit real keys. Leaderboard ranks change quickly.',
    ]

    out = {
        'updated': TODAY,
        'snapshot_note': 'Public, dated snapshot of free leaderboard wallets. Not a live feed.',
        'credit_budget': {
            'daily_cap': 30000,
            'monthly_free_plan': 1000000,
            'shrink_size': 150,
            'shrink_ratio': 0.8,
        },
        'counts': {
            'sol_stream': len(stream),
            'sol_reserve': len(reserve),
            'bsc': len(bsc_out),
            'rejected': dict(rejected),
            'narratives_stream': dict(narr_counts),
            'sources': {
                'gmgn_solwallets_json_date': gmgn_date,
                'gmgn_bscwallets_json_date': bsc_date,
                'kolscan_leaderboard_unique': n_ks,
                'verified_kols': n_ver,
                'yksanjo_rows': n_yk,
                'frozen_rows': n_fr,
            },
        },
        'notes': notes,
        'wallets': [emit_wallet(r, stream=True) for r in stream]
                  + [emit_wallet(r, stream=False) for r in reserve],
        'bsc': bsc_out,
    }
    dest = HERE / 'smart_wallets.json'
    dest.write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({
        'wrote': str(dest),
        'sol_stream': len(stream),
        'sol_reserve': len(reserve),
        'bsc': len(bsc_out),
        'rejected': dict(rejected),
        'narratives_stream': dict(narr_counts),
        'bytes': dest.stat().st_size,
    }, indent=2))


if __name__ == '__main__':
    main()
