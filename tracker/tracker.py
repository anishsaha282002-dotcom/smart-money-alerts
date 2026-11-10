#!/usr/bin/env python3
"""
Memecoin narrative tracker (research/signals only - never trades, never posts).

X data comes from the X MCP tools, which only the agent can call, so each run has 3 steps:
  1) python3 tracker.py plan                -> runs/<RUN>/plan.json  (X search queries to execute)
     agent runs each query with x.search_posts_all, saves raw output as runs/<RUN>/posts_<n>.txt
  2) python3 tracker.py extract --run <RUN> -> runs/<RUN>/counts_plan.json (CA mention-count queries)
     agent runs each with x.get_posts_counts_recent (granularity=hour), saves runs/<RUN>/counts_<mint>.txt
  3) python3 tracker.py score --run <RUN>   -> runs/<RUN>/report.md  (+ state.db updated)
v2 (10 Nov 2026): narrative layer (narratives.py), Chinese/BSC coverage (zh callers, catalysts, zh keyword search,
GoPlus security for BSC), ticker->CA resolution, Jupiter organic-volume (wash) check, hard X budget per run.
Market data: DexScreener (prices/liquidity/volume/txns), RugCheck (authorities, holders, insiders),
GeckoTerminal (fallback + OHLCV for backtest).
Optional read-only boosters (env keys, skipped if missing): Helius Free Parsed Streams worker
(stream_worker.py) plus a Parsed Events poll fallback, and GMGN OpenAPI smart-money / KOL feeds
(never trades, never signs, never links a wallet). pump.fun's own API is Cloudflare-blocked from this box.
"""
import argparse, json, os, re, sqlite3, sys, time, glob, datetime as dt
import urllib.request, urllib.error
from xparse import load_x_json, posts_from
import narratives as NARR
import smartmoney as SM
import pumpfun_callouts as PFC

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'state.db')
RUNS = os.path.join(HERE, 'runs')
UA = {'User-Agent': 'Mozilla/5.0 (memecoin-tracker research)'}

# ---------------- thresholds (documented in README.md) ----------------
CFG = dict(
    caller_window_h=6,        # callers must mention within this window
    min_callers=2,            # distinct, non-flagged tracked callers
    min_liq_usd=10_000,       # liquidity floor
    min_mcap=20_000, max_mcap=25_000_000,
    max_mult_from_first_call=10.0,  # skip if already 10x+ since first tracked call
    max_h1_change_pct=300,    # skip vertical candles (+300% in 1h)
    min_age_min=15, max_age_days=7,
    max_top10_pct=30.0,       # top-10 non-AMM holders
    max_creator_pct=5.0,
    min_mentions_1h=5, min_velocity_ratio=2.0,   # last-hour mentions vs avg of prior 6h
    strong_mentions_1h=15, strong_velocity_ratio=3.0,
    min_buy_sell_ratio=1.0,   # h1 buys / sells
    # SELL
    sell_mention_drop=0.60,   # last-3h avg mentions down >=60% from peak hour
    sell_quiet_h=12,          # no tracked caller mention in 12h
    sell_vol_ratio=0.30,      # vol_h1 < 30% of avg hourly vol over h6
    sell_buy_sell_ratio=0.8,
    sell_liq_drop=0.30,       # liquidity down >=30% from signal
    sell_creator_drop=0.50,   # creator balance down >=50% since signal
    stop_loss=-0.35, trail_from_peak=-0.30, take_profit_mult=2.0,
)
NEG = re.compile(r'\b(rug|rugged|rugging|dump(ed|ing)?|sold|selling|exited|jeet(ed|s)?|dead|scam|bundled|cabal dump|farm(ed)?)\b', re.I)
CA_RE = re.compile(r'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])')
TICK_RE = re.compile(r'(?<![\w$])\$([A-Za-z][A-Za-z0-9]{1,11}|[\u4e00-\u9fff]{1,8})')
EVM_RE = re.compile(r'(?<![0-9a-fA-Fx])(0x[a-fA-F0-9]{40})(?![0-9a-fA-F])')
def chain_of(addr): return 'bsc' if addr.startswith('0x') else 'solana'
def norm(addr): return addr.lower() if addr.startswith('0x') else addr
IGNORE_MINTS = {'So11111111111111111111111111111111111111112','EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v','Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'}
MAJOR_TICKERS = {'SOL','BTC','ETH','USDC','USDT','BNB','XRP','DOGE','HYPE','SPX','TSLA','NVDA','SPY','QQQ','PUMP','JUP','BONK','WIF'}
X_FILTER_ZH = '(CA OR 0x OR bsc OR BNB OR 土狗 OR 金狗 OR meme OR 冲 OR 四妹 OR url:four.meme OR url:gmgn.ai OR url:dexscreener.com OR url:debot.ai OR url:web3.binance.com)'
ZH_KEYWORD_Q = '(土狗 OR 金狗 OR 打狗 OR 四妹 OR 内盘 OR 外盘 OR 冲了 OR 埋伏 OR 叙事) (CA OR 0x OR bsc OR meme OR 币安) lang:zh -is:retweet -is:reply'
X_FILTER = '(CA OR solana OR pump OR pumpfun OR url:pump.fun OR url:dexscreener.com OR url:gmgn.ai OR url:axiom.trade OR url:fomo.family OR url:photon-sol.tinyastro.io OR url:jup.ag)'

def now(): return dt.datetime.now(dt.timezone.utc)
def iso(t): return t.strftime('%Y-%m-%dT%H:%M:%SZ')
def parse_t(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))

def http_json(url, tries=3, sleep=2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(sleep * (i + 2) * 3); continue
            if e.code in (404, 400): return None
            time.sleep(sleep)
        except Exception:
            time.sleep(sleep)
    return None

def resolve_tco(url):
    try:
        req = urllib.request.Request(url, headers=UA, method='HEAD')
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k): return None
        op = urllib.request.build_opener(NoRedir)
        try:
            op.open(req, timeout=8)
        except urllib.error.HTTPError as e:
            return e.headers.get('Location') or url
    except Exception:
        pass
    return url

# ---------------- state ----------------
def db():
    c = sqlite3.connect(DB)
    c.executescript('''
    create table if not exists meta(k text primary key, v text);
    create table if not exists posts(id text primary key, username text, created_at text, text text, url text, run text);
    create table if not exists mentions(post_id text, mint text, username text, created_at text, tier text, flagged int, negative int, primary key(post_id, mint));
    create table if not exists tickers(post_id text, ticker text, username text, created_at text, primary key(post_id, ticker));
    create table if not exists coins(mint text primary key, symbol text, name text, first_seen text, first_call_url text,
        first_seen_price real, first_seen_mcap real, status text default 'watch', signal_time text, signal_price real,
        signal_liq real, signal_creator_bal real, peak_price_since_signal real, peak_hourly_mentions int default 0, notes text);
    create table if not exists callout_links(post_id text, url text, username text, created_at text, primary key(post_id, url));
    create table if not exists discovered(mint text primary key, ts text, source text, note text);
    create table if not exists snapshots(mint text, ts text, run text, price real, mcap real, liq real, vol_h1 real, vol_h6 real,
        buys_h1 int, sells_h1 int, holders int, mentions_1h int, mentions_prior6_avg real, decision text, reasons text);
    create table if not exists shill(key text, ts text, n_authors int, sample_url text, primary key(key, ts));
    create table if not exists ticker_resolved(ticker text primary key, mint text, chain text, ts text, n_candidates int, note text);
    ''')
    try: c.execute('alter table coins add column chain text')
    except Exception: pass
    return c

def meta_get(c, k, d=None):
    r = c.execute('select v from meta where k=?', (k,)).fetchone(); return r[0] if r else d
def meta_set(c, k, v): c.execute('insert or replace into meta values(?,?)', (k, str(v))); c.commit()

def load_callers():
    j = json.load(open(os.path.join(HERE, 'callers.json')))
    tiers = {x['handle'].lower(): x['tier'] for x in j['callers']}
    flagged = {x['handle'].lower(): x['why'] for x in j['flagged']}
    return j, tiers, flagged

def catalyst_handles(j): return [x['handle'] for x in j.get('catalysts', [])]

# ---------------- step 1: plan ----------------
def cmd_plan(a):
    c = db(); j, tiers, flagged = load_callers()
    def chunk(handles, filt):
        chunks, cur = [], []
        for h in handles:
            trial = cur + [h]
            q = '(' + ' OR '.join('from:' + x for x in trial) + ') ' + filt + ' -is:retweet'
            if len(q) > 1000: chunks.append(cur); cur = [h]
            else: cur = trial
        if cur: chunks.append(cur)
        return chunks
    en = [x['handle'] for x in j['callers'] if x.get('lang', 'en') == 'en'] + [x['handle'] for x in j['flagged']]
    zh = [x['handle'] for x in j['callers'] if x.get('lang') == 'zh']
    groups = [(ch, X_FILTER, a.max_pages) for ch in chunk(en, X_FILTER)] + [(ch, X_FILTER_ZH, 1) for ch in chunk(zh, X_FILTER_ZH)]
    run = a.run or now().strftime('%Y%m%dT%H%MZ')
    rd = os.path.join(RUNS, run); os.makedirs(rd, exist_ok=True)
    since_id = meta_get(c, 'since_id')
    queries = []
    base = {'max_results': 25, 'sort_order': 'recency', 'post.fields': 'created_at,public_metrics,author_id,note_tweet,lang,entities',
            'expansions': 'author_id', 'user.fields': 'username'}
    def add(query, pages, kind):
        q = dict(base, query=query)
        sid = meta_get(c, 'since_id_' + kind) or (since_id if kind == 'callers_en' else None)
        if sid: q['since_id'] = sid
        else: q['start_time'] = iso(now() - dt.timedelta(hours=a.lookback_h))
        i = len(queries)
        queries.append({'tool': 'x.search_posts_all', 'kind': kind, 'save_as': f'posts_{i}.txt', 'args': q,
                        'paginate': (f'follow meta.next_token up to {pages} pages total; save extra pages as posts_{i}_p2.txt' if pages > 1 else 'first page only')})
    for ch, filt, pages in groups:
        add('(' + ' OR '.join('from:' + x for x in ch) + ') ' + filt + ' -is:retweet', pages, 'callers_zh' if filt == X_FILTER_ZH else 'callers_en')
    cats = catalyst_handles(j)
    if cats and not a.no_zh: add('(' + ' OR '.join('from:' + x for x in cats) + ') -is:retweet', 1, 'catalysts')
    if not a.no_zh: add(ZH_KEYWORD_Q, 1, 'zh_keywords')
    json.dump({'run': run, 'queries': queries}, open(os.path.join(rd, 'plan.json'), 'w'), indent=1)
    print(json.dumps({'run': run, 'dir': rd, 'n_queries': len(queries), 'max_search_calls': sum(2 if 'up to 2' in q['paginate'] else 1 for q in queries),
                      'next': f'.venv/bin/python narratives.py collect --run {run}  (then run the plan queries)'}, indent=1))

# ---------------- step 2: extract ----------------
CALLOUT_CACHE = os.path.join(HERE, 'callouts_cache.json')
def load_callout_cache():
    try: return json.load(open(CALLOUT_CACHE))
    except Exception: return {}

def extract_from_post(p):
    texts = [p['text']] + p.get('urls', [])
    for u in re.findall(r'https://t\.co/\w+', p['text'])[:4]:
        r = resolve_tco(u)
        if r and 'twitter.com' not in r and 'x.com' not in r: texts.append(r)
    blob = ' '.join(texts)
    callouts = sorted(set(re.findall(r'https://pump\.fun/c/[0-9a-f-]{36}/[\w.-]+', blob)))
    cache = load_callout_cache()
    for cu in callouts:
        if cache.get(cu): texts.append(cache[cu])
    blob = ' '.join(texts)
    p['_callouts'] = callouts
    mints = []
    for m in EVM_RE.findall(blob):
        m = m.lower()
        if m not in mints: mints.append(m)
    blob_no_evm = EVM_RE.sub(' ', blob)
    for m in CA_RE.findall(blob_no_evm):
        if m in IGNORE_MINTS or m.startswith('0x'): continue
        if m not in mints: mints.append(m)
    ticks = sorted({t.upper() for t in TICK_RE.findall(p['text'])} - MAJOR_TICKERS)
    return mints, ticks

def cmd_extract(a):
    c = db(); j, tiers, flagged = load_callers()
    cats = {h.lower() for h in catalyst_handles(j)}
    rd = os.path.join(RUNS, a.run)
    files = sorted(glob.glob(os.path.join(rd, 'posts_*.txt')))
    searches_used = len(files)
    max_id = int(meta_get(c, 'since_id', '0') or 0); n_posts = 0; new_mints = set()
    try: kinds = {q['save_as'].split('.')[0]: q.get('kind', 'callers_en') for q in json.load(open(os.path.join(rd, 'plan.json')))['queries']}
    except Exception: kinds = {}
    kind_max = {}
    for f in files:
        try: o = load_x_json(f)
        except Exception as e: print('skip', f, e); continue
        kind = kinds.get(os.path.basename(f).split('.')[0].split('_p')[0], 'callers_en')
        for p in posts_from(o):
            n_posts += 1; max_id = max(max_id, int(p['id'])); kind_max[kind] = max(kind_max.get(kind, 0), int(p['id']))
            c.execute('insert or ignore into posts values(?,?,?,?,?,?)', (p['id'], p['username'], p['created_at'], p['text'], p['url'], a.run))
            h = (p['username'] or '').lower()
            if h in cats: continue          # catalyst posts are stored for keyword matching only
            mints, ticks = extract_from_post(p)
            for m in mints:
                c.execute('insert or ignore into mentions values(?,?,?,?,?,?,?)',
                          (p['id'], m, p['username'], p['created_at'], tiers.get(h, 'X'), 1 if h in flagged else 0, 1 if NEG.search(p['text']) else 0))
                if not c.execute('select 1 from coins where mint=?', (m,)).fetchone():
                    c.execute('insert into coins(mint, first_seen, first_call_url, chain) values(?,?,?,?)', (m, p['created_at'], p['url'], chain_of(m)))
                new_mints.add(m)
            for cu in p.get('_callouts', []):
                c.execute('insert or ignore into callout_links values(?,?,?,?)', (p['id'], cu, p['username'], p['created_at']))
            for t in ticks:
                c.execute('insert or ignore into tickers values(?,?,?,?)', (p['id'], t, p['username'], p['created_at']))
    c.commit()
    shills = detect_shill(c, a.run)
    if max_id: meta_set(c, 'since_id', max_id)
    for k, v in kind_max.items(): meta_set(c, 'since_id_' + k, v)
    resolved = resolve_tickers(c, tiers, flagged) if a.resolve_tickers else []
    # which coins need mention counts: mentioned in last 48h by a tracked caller, or active positions
    cutoff = iso(now() - dt.timedelta(hours=48))
    rows = c.execute('''select mint, count(distinct lower(username)) n from mentions where created_at>=? and flagged=0 and tier in ('A','B')
                        group by mint order by n desc''', (cutoff,)).fetchall()
    active = [r[0] for r in c.execute("select mint from coins where status='active'")]
    want = [r[0] for r in rows][:a.max_counts]
    nj_path = os.path.join(rd, 'narratives.json')
    nj = json.load(open(nj_path)) if os.path.exists(nj_path) else {}
    # narrative discovery: GeckoTerminal trending Solana pools (free, no key) - pools created in the last 7 days
    disc = []
    if a.discover:
        d = http_json('https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?page=1') or {}
        for pool in d.get('data', []):
            at = pool.get('attributes', {}); rel = pool.get('relationships', {})
            base = (rel.get('base_token', {}).get('data') or {}).get('id', '').replace('solana_', '')
            created = at.get('pool_created_at')
            if not base or not created: continue
            age_h = (now() - parse_t(created)).total_seconds() / 3600
            if age_h <= 168 and base not in want and base not in disc:
                disc.append(base)
                c.execute('insert or replace into discovered values(?,?,?,?)', (base, iso(now()), 'gecko_trending', at.get('name')))
                if not c.execute('select 1 from coins where mint=?', (base,)).fetchone():
                    c.execute('insert into coins(mint, first_seen, first_call_url, chain) values(?,?,?,?)', (base, iso(now()), 'GeckoTerminal trending (no caller yet)', 'solana'))
            if len(disc) >= a.discover: break
        c.commit()
    # narrative leaders (top-2 coins of the top narratives) become scored candidates; no per-CA X call unless budget is left
    nleaders = []
    for n in (nj.get('narratives') or [])[:a.narrative_leaders_from]:
        for l in n['leaders'][:2]:
            k = norm(l['address'])
            if (l.get('liq') or 0) < 10000 or (l.get('age_h') is not None and l['age_h'] > 168) or k in nleaders: continue
            nleaders.append(k)
            c.execute('insert or replace into discovered values(?,?,?,?)', (k, iso(now()), 'narrative:' + n['narrative'], l.get('symbol')))
            if not c.execute('select 1 from coins where mint=?', (k,)).fetchone():
                c.execute('insert into coins(mint, first_seen, first_call_url, chain) values(?,?,?,?)', (k, iso(now()), f"narrative leader: {n['narrative']} (no caller yet)", l['chain']))
    c.commit()
    # ---- hard X budget: searches already spent + count queries <= x_budget
    budget = max(0, a.x_budget - searches_used)
    order = [m for m in active] + [m for m in want if m not in active]
    nq = (nj.get('x_count_queries') or [])[:a.narrative_counts]
    cq = []
    for m in order:
        if len(cq) >= budget: break
        cq.append({'tool': 'x.get_posts_counts_recent', 'save_as': f'counts_{m}.txt', 'args': {'query': m, 'granularity': 'hour', 'start_time': iso(now() - dt.timedelta(hours=72))}})
    for q in nq:
        if len(cq) >= budget: break
        cq.append({k: q[k] for k in ('tool', 'save_as', 'args', 'narrative')})
    for m in disc + nleaders:
        if len(cq) >= budget: break
        if any(x['save_as'] == f'counts_{m}.txt' for x in cq): continue
        cq.append({'tool': 'x.get_posts_counts_recent', 'save_as': f'counts_{m}.txt', 'args': {'query': m, 'granularity': 'hour', 'start_time': iso(now() - dt.timedelta(hours=72))}})
    want += disc + nleaders
    for m in active:
        if m not in want: want.append(m)
    cache = load_callout_cache()
    unresolved = sorted({r[0] for r in c.execute('select url from callout_links where created_at>=?', (cutoff,)) if r[0] not in cache})
    json.dump({'note': 'Fetch each with WebFetch; the "Page image" URL is https://pump.fun/callouts/<MINT>/... Add {url: mint} to callouts_cache.json, then re-run extract.', 'urls': unresolved},
              open(os.path.join(rd, 'callouts_to_resolve.json'), 'w'), indent=1)
    json.dump({'run': a.run, 'x_budget': a.x_budget, 'search_calls_used': searches_used, 'queries': cq}, open(os.path.join(rd, 'counts_plan.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({'posts_parsed': n_posts, 'shill_campaign_keys': shills, 'mints_seen_this_run': len(new_mints), 'tickers_resolved': resolved, 'gecko_discovered': disc,
                      'narrative_leaders': nleaders, 'pump_callout_links_to_resolve': len(unresolved), 'search_calls_used': searches_used,
                      'counts_queries': len(cq), 'x_calls_total_this_run': searches_used + len(cq)}, ensure_ascii=False, indent=1))

def _shingles(t):
    t = re.sub(r'https?://\S+|@\w+|#\w+|\s+', '', t or '').lower()
    return {t[i:i + 5] for i in range(max(0, len(t) - 4))}

def detect_shill(c, run, min_authors=3, sim=0.45):
    """Copy-paste campaigns: >=3 different accounts posting near-identical text in this run's results.
    Every CA and $ticker in those posts is marked as shilled (a BUY blocker)."""
    rows = c.execute('select id, username, text, url from posts where run=?', (run,)).fetchall()
    sh = [(r, _shingles(r[2])) for r in rows]
    found = []
    for i, (r, a_) in enumerate(sh):
        if len(a_) < 30: continue
        authors = {r[1].lower()}
        for r2, b_ in sh:
            if r2[0] == r[0] or len(b_) < 30: continue
            if len(a_ & b_) / len(a_ | b_) >= sim: authors.add(r2[1].lower())
        exact = {r2[1].lower() for r2, b_ in sh if r2[0] != r[0] and len(b_) >= 30 and len(a_ & b_) / len(a_ | b_) >= 0.9} | {r[1].lower()}
        if len(authors) >= min_authors or len(exact) >= 2:
            authors = authors | exact
            keys = [m.lower() for m in EVM_RE.findall(r[2])] + [m for m in CA_RE.findall(EVM_RE.sub(' ', r[2])) if not m.startswith('0x')] + ['$' + t.upper() for t in TICK_RE.findall(r[2])]
            keys += ['$' + t.upper() for t in re.findall(r'#([A-Za-z][A-Za-z0-9]{1,11})\b', r[2]) if t.upper() not in MAJOR_TICKERS | {'MEME', 'CRYPTO', 'BTC', 'ETH'}]
            for k in keys:
                c.execute('insert or replace into shill values(?,?,?,?)', (k, iso(now()), len(authors), r[3])); found.append(k)
    c.commit()
    return sorted(set(found))

def resolve_tickers(c, tiers, flagged, hours=24):
    """Callers increasingly post $TICKER without a CA. Resolve tickers named by >=2 tracked callers (or 1 tier-A)
    to the highest-volume Solana/BSC pair with that exact symbol (liq >= $5K, age <= 7d) via DexScreener search.
    Copycat risk is reported (n_candidates)."""
    out = []
    rows = c.execute('select ticker, group_concat(post_id), group_concat(username) from tickers where created_at>=? group by ticker', (iso(now() - dt.timedelta(hours=hours)),)).fetchall()
    for tk, pids, users in rows:
        us = {u.lower() for u in (users or '').split(',') if u and u.lower() in tiers and u.lower() not in flagged}
        if not (len(us) >= 2 or any(tiers[u] == 'A' for u in us)): continue
        prev = c.execute('select mint from ticker_resolved where ticker=?', (tk,)).fetchone()
        if prev: mint = prev[0]
        else:
            d = http_json('https://api.dexscreener.com/latest/dex/search?q=' + urllib.request.quote(tk)) or {}
            cands = [p for p in d.get('pairs') or [] if p.get('chainId') in ('solana', 'bsc') and (p.get('baseToken') or {}).get('symbol', '').upper().lstrip('$') == tk
                     and ((p.get('liquidity') or {}).get('usd') or 0) >= 5000 and p.get('pairCreatedAt') and (time.time() * 1000 - p['pairCreatedAt']) < 7 * 86400 * 1000]
            if not cands: continue
            addrs = {norm(p['baseToken']['address']) for p in cands}
            best = max(cands, key=lambda p: (p.get('volume') or {}).get('h24') or 0)
            mint = norm(best['baseToken']['address'])
            c.execute('insert or replace into ticker_resolved values(?,?,?,?,?,?)', (tk, mint, best['chainId'], iso(now()), len(addrs), f'{len(addrs)} coins share this ticker'))
            if not c.execute('select 1 from coins where mint=?', (mint,)).fetchone():
                c.execute('insert into coins(mint, first_seen, first_call_url, chain, notes) values(?,?,?,?,?)', (mint, iso(now()), f'resolved from ${tk}', best['chainId'], f'ticker-resolved; {len(addrs)} candidates'))
            time.sleep(0.4)
        for pid in (pids or '').split(','):
            r = c.execute('select username, created_at, text from posts where id=?', (pid,)).fetchone()
            if not r: continue
            h = (r[0] or '').lower()
            c.execute('insert or ignore into mentions values(?,?,?,?,?,?,?)', (pid, mint, r[0], r[1], tiers.get(h, 'X'), 1 if h in flagged else 0, 1 if NEG.search(r[2] or '') else 0))
        out.append({'ticker': tk, 'mint': mint})
    c.commit()
    return out

# ---------------- market data ----------------
def dexscreener(mints):
    out = {}
    by_chain = {}
    for m in mints: by_chain.setdefault(chain_of(m), []).append(m)
    for chain, ms in by_chain.items():
        out.update(_dexscreener(chain, ms))
    return out

def _dexscreener(chain, mints):
    out = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        d = http_json(f'https://api.dexscreener.com/tokens/v1/{chain}/' + ','.join(chunk)) or []
        for p in d:
            m = norm(p['baseToken']['address'])
            if m not in chunk: continue
            if m not in out or (p.get('liquidity') or {}).get('usd', 0) > (out[m].get('liquidity') or {}).get('usd', 0):
                out[m] = p
            out[m].setdefault('_dexes', set()).add(p.get('dexId'))
        time.sleep(0.3)
    return out

def gecko(mint):
    d = http_json(f'https://api.geckoterminal.com/api/v2/networks/{chain_of(mint)}/tokens/{mint}')
    return (d or {}).get('data', {}).get('attributes')

def rugcheck(mint):
    d = http_json(f'https://api.rugcheck.xyz/v1/tokens/{mint}/report')
    if not d: return None
    known = d.get('knownAccounts') or {}
    amm_owners = {k for k, v in known.items() if (v or {}).get('type') in ('AMM', 'LOCKER')}
    for mk in d.get('markets') or []:
        for k in ('liquidityA', 'liquidityB', 'pubkey'):
            if mk.get(k): amm_owners.add(mk[k])
    top = [h for h in (d.get('topHolders') or []) if h.get('owner') not in amm_owners and h.get('address') not in amm_owners]
    top10 = sum(h.get('pct', 0) for h in top[:10])
    supply = ((d.get('token') or {}).get('supply')) or 0
    cb = d.get('creatorBalance') or 0
    creator_pct = 100.0 * cb / supply if supply else None
    dangers = [r.get('name') for r in d.get('risks') or [] if r.get('level') == 'danger']
    warns = [r.get('name') for r in d.get('risks') or [] if r.get('level') == 'warn']
    lp_locked = max([((mk.get('lp') or {}).get('lpLockedPct') or 0) for mk in d.get('markets') or []] or [0])
    return dict(mint_auth=d.get('mintAuthority'), freeze_auth=d.get('freezeAuthority'), holders=d.get('totalHolders'),
                top10=top10, creator_bal=cb, creator_pct=creator_pct, dangers=dangers, warns=warns, rugged=d.get('rugged'),
                insiders=d.get('graphInsidersDetected') or 0, lp_locked=lp_locked, score=d.get('score_normalised'))

def goplus_bsc(addr):
    """GoPlus token security (free, no key) for BSC tokens; returns the same shape as rugcheck()."""
    d = http_json(f'https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses={addr}')
    r = ((d or {}).get('result') or {}).get(addr.lower())
    if not r or r.get('holder_count') in (None, '', '0'): return None
    f = lambda k: str(r.get(k) or '0') == '1'
    dead = {'0x000000000000000000000000000000000000dead', '0x0000000000000000000000000000000000000000'}
    top = [h for h in r.get('holders') or [] if not str(h.get('is_contract')) == '1' and (h.get('address') or '').lower() not in dead]
    top10 = sum(float(h.get('percent') or 0) for h in top[:10]) * 100
    dangers = [k for k in ('is_honeypot', 'cannot_sell_all', 'hidden_owner', 'can_take_back_ownership', 'owner_change_balance', 'selfdestruct') if f(k)]
    for k in ('buy_tax', 'sell_tax'):
        try:
            if float(r.get(k) or 0) > 0.10: dangers.append(f'{k} {float(r[k]):.0%}')
        except Exception: pass
    owner = (r.get('owner_address') or '').lower()
    mintable = f('is_mintable') and owner not in dead and owner != ''
    warns = [k for k in ('transfer_pausable', 'slippage_modifiable', 'is_proxy', 'trading_cooldown') if f(k)]
    return dict(mint_auth='mintable by owner' if mintable else None, freeze_auth=None, holders=int(r.get('holder_count') or 0),
                top10=top10, creator_bal=float(r.get('creator_balance') or 0), creator_pct=float(r.get('creator_percent') or 0) * 100,
                dangers=dangers, warns=warns, rugged=f('is_honeypot'), insiders=0, lp_locked=None, score=None, source='GoPlus')

def jup_organic(mints):
    """Jupiter organic score (free): 'low' means volume looks bot/wash-traded."""
    out = {}
    sol = [m for m in mints if chain_of(m) == 'solana']
    for i in range(0, len(sol), 50):
        d = http_json('https://lite-api.jup.ag/tokens/v2/search?query=' + ','.join(sol[i:i + 50])) or []
        for x in d: out[x.get('id')] = (x.get('organicScoreLabel'), x.get('organicScore'))
    return out

def load_counts(rd, mint):
    f = os.path.join(rd, f'counts_{mint}.txt')
    if not os.path.exists(f): return None
    try: o = load_x_json(f)
    except Exception: return None
    b = sorted(o.get('data') or [], key=lambda x: x['start'])
    vals = [x.get('tweet_count', 0) for x in b]
    if not vals: return None
    # last bucket is the current partial hour; scale it to a full hour estimate is noisy, so use the last COMPLETE hour
    full = vals[:-1] if len(vals) > 1 else vals
    last1 = full[-1] if full else 0
    prior6 = full[-7:-1] if len(full) >= 2 else []
    prior6_avg = sum(prior6) / len(prior6) if prior6 else 0.0
    last3_avg = sum(full[-3:]) / min(3, len(full)) if full else 0
    peak = max(full) if full else 0
    return dict(last1=last1, prior6_avg=prior6_avg, last3_avg=last3_avg, peak=peak, total=sum(vals), hours=len(vals))

# ---------------- step 3: score ----------------
def fmt_usd(x):
    if x is None: return 'n/a'
    return f'${x/1e6:.2f}M' if x >= 1e6 else f'${x/1e3:.1f}K'

def cmd_score(a):
    c = db(); j, tiers, flagged = load_callers()
    try:
        lb_snap = PFC.load_snapshot()
    except Exception:
        lb_snap = {}
    rd = os.path.join(RUNS, a.run); T = now()
    cutoff48 = iso(T - dt.timedelta(hours=48)); cutoffW = iso(T - dt.timedelta(hours=CFG['caller_window_h']))
    cand = [r[0] for r in c.execute('select distinct mint from mentions where created_at>=?', (cutoff48,))]
    cand += [r[0] for r in c.execute('select mint from discovered where ts>=?', (iso(T - dt.timedelta(hours=24)),))]
    active = [r[0] for r in c.execute("select mint from coins where status='active'")]
    mints = list(dict.fromkeys(cand + active))
    ds = dexscreener(mints) if mints else {}
    org = jup_organic(mints) if mints else {}
    sm_bundle = SM.collect(mints, run_dir=rd)
    nlist, by_addr = NARR.finalize(rd, c)
    feed_src = {}
    try:
        for t in json.load(open(os.path.join(rd, 'feed_tokens.json'))): feed_src[norm(t['address'])] = set(t['sources'])
    except Exception: pass
    disc_src = dict(c.execute('select mint, source from discovered').fetchall())
    buys, watch, sells, holds, rejects = [], [], [], [], []
    board = []
    for m in mints:
        coin = dict(zip([d[0] for d in c.execute('select * from coins where mint=?', (m,)).description],
                        c.execute('select * from coins where mint=?', (m,)).fetchone()))
        p = ds.get(m); g = None
        if not p:
            g = gecko(m); time.sleep(2.1)
        rc = goplus_bsc(m) if chain_of(m) == 'bsc' else rugcheck(m); time.sleep(0.8)
        if not p and not g and not rc:
            rejects.append((m, None, ['not a tradable Solana/BSC token (no DexScreener/Gecko/RugCheck/GoPlus data)'])); continue
        sym = (p or {}).get('baseToken', {}).get('symbol') or (g or {}).get('symbol') or '?'
        name = (p or {}).get('baseToken', {}).get('name') or (g or {}).get('name') or '?'
        price = float((p or {}).get('priceUsd') or (g or {}).get('price_usd') or 0) or None
        mcap = (p or {}).get('marketCap') or (p or {}).get('fdv') or (float((g or {}).get('fdv_usd') or 0) or None)
        liq = ((p or {}).get('liquidity') or {}).get('usd')
        if liq is None and g: liq = float(g.get('total_reserve_in_usd') or 0)
        vol = (p or {}).get('volume') or {}; tx = ((p or {}).get('txns') or {}).get('h1') or {}
        vol_h1, vol_h6 = vol.get('h1'), vol.get('h6')
        b1, s1 = tx.get('buys', 0), tx.get('sells', 0)
        pc = (p or {}).get('priceChange') or {}
        created = (p or {}).get('pairCreatedAt'); age_min = (T.timestamp() * 1000 - created) / 60000 if created else None
        dexes = sorted((p or {}).get('_dexes') or [])
        bonding = dexes == ['pumpfun']
        url = (p or {}).get('url') or f'https://dexscreener.com/{chain_of(m)}/{m}'
        narrs = sorted(by_addr.get(m, []), key=lambda d: (d['leader_rank'] or 9))
        organic = org.get(m)
        organic_feeds = sorted((feed_src.get(m) or set()) & NARR.ORGANIC)
        if coin['first_seen_price'] is None and price:
            c.execute('update coins set first_seen_price=?, first_seen_mcap=? where mint=?', (price, mcap, m))
            coin['first_seen_price'] = price
        c.execute('update coins set symbol=?, name=? where mint=?', (sym, name, m))
        ment = c.execute('select username, created_at, tier, flagged, negative, post_id from mentions where mint=? order by created_at', (m,)).fetchall()
        callers_w = sorted({r[0].lower() for r in ment if r[1] >= cutoffW and not r[3] and r[2] in ('A', 'B')})
        callers_all = sorted({r[0] for r in ment})
        neg_recent = [r[0] for r in ment if r[4] and r[1] >= iso(T - dt.timedelta(hours=24))]
        last_caller_post = max([r[1] for r in ment if not r[3]] or [None]) if ment else None
        cnt = load_counts(rd, m)
        if cnt and cnt['peak'] > (coin['peak_hourly_mentions'] or 0):
            c.execute('update coins set peak_hourly_mentions=? where mint=?', (cnt['peak'], m)); coin['peak_hourly_mentions'] = cnt['peak']
        mult = (price / coin['first_seen_price']) if price and coin['first_seen_price'] else None
        info = dict(mint=m, sym=sym, name=name, url=url, price=price, mcap=mcap, liq=liq, vol_h1=vol_h1, vol_h6=vol_h6, b1=b1, s1=s1,
                    pc=pc, age_min=age_min, bonding=bonding, dexes=dexes, rc=rc, cnt=cnt, callers_w=callers_w,
                    callers_all=callers_all, mult=mult, first_call=coin['first_call_url'], neg=neg_recent,
                    flagged_callers=sorted({r[0] for r in ment if r[3]}), chain=chain_of(m), narrs=narrs, organic=organic,
                    organic_feeds=organic_feeds, disc=disc_src.get(m),
                    sm=(sm_bundle.get('by_mint') or {}).get(norm(m)) or SM.empty_hit())
        info['confidence'] = (info['sm'] or {}).get('confidence') or 'standard'
        board.append(info)
        reasons = []
        if coin['status'] == 'active':
            # ---------------- SELL evaluation ----------------
            hard, soft = [], []
            sp = coin['signal_price']; peak = max(coin['peak_price_since_signal'] or 0, price or 0)
            c.execute('update coins set peak_price_since_signal=? where mint=?', (peak, m))
            if price and sp:
                r = price / sp - 1
                if r <= CFG['stop_loss']: hard.append(f'stop-loss: {r:+.0%} from signal price')
                if peak and price / peak - 1 <= CFG['trail_from_peak'] and peak >= sp * 1.3: hard.append(f'trailing stop: {price/peak-1:+.0%} from post-signal peak')
                if r >= CFG['take_profit_mult'] - 1: soft.append(f'take-profit zone: {r+1:.1f}x from signal (suggest selling at least half)')
            if (rc or {}).get('rugged'): hard.append('RugCheck marks token rugged')
            if cnt and coin['peak_hourly_mentions'] and cnt['last3_avg'] <= (1 - CFG['sell_mention_drop']) * coin['peak_hourly_mentions']:
                soft.append(f"mentions fading: last-3h avg {cnt['last3_avg']:.1f}/h vs peak {coin['peak_hourly_mentions']}/h")
            if last_caller_post and parse_t(last_caller_post) < T - dt.timedelta(hours=CFG['sell_quiet_h']):
                soft.append(f'tracked callers quiet for >{CFG["sell_quiet_h"]}h')
            if neg_recent: soft.append('negative caller posts: ' + ', '.join(sorted(set(neg_recent))))
            if narrs and all(d['status'] == 'FADING' for d in narrs): soft.append('narrative fading: ' + ', '.join(d['narrative'] for d in narrs))
            sm = info.get('sm') or {}
            if sm.get('sm_sell') or sm.get('kol_sell'):
                soft.append('smart-money/KOL selling: ' + (sm.get('sell_reason') or 'GMGN sell in last 1h'))
            if vol_h1 is not None and vol_h6 and vol_h1 < CFG['sell_vol_ratio'] * vol_h6 / 6: soft.append('volume drying up (h1 < 30% of h6 hourly avg)')
            if s1 and b1 / max(s1, 1) < CFG['sell_buy_sell_ratio']: soft.append(f'sell pressure: h1 buys {b1} vs sells {s1}')
            if liq is not None and coin['signal_liq'] and liq < (1 - CFG['sell_liq_drop']) * coin['signal_liq']: hard.append(f'liquidity drained {liq/coin["signal_liq"]-1:+.0%} since signal')
            if rc and coin['signal_creator_bal'] and rc['creator_bal'] < (1 - CFG['sell_creator_drop']) * coin['signal_creator_bal']: hard.append('creator/dev wallet sold >=50% since signal')
            decision = 'SELL' if hard or len(soft) >= 2 else 'HOLD/WATCH'
            reasons = hard + soft
            if decision == 'SELL':
                c.execute("update coins set status='sold' where mint=?", (m,)); sells.append(info | {'reasons': reasons})
            else: holds.append(info | {'reasons': reasons or ['no exit condition hit']})
        else:
            # ---------------- BUY evaluation ----------------
            fails, passes = [], []
            tierA_w = [h for h in callers_w if tiers.get(h) == 'A']
            spike = bool(cnt and cnt['last1'] >= CFG['strong_mentions_1h'] and cnt['last1'] >= CFG['strong_velocity_ratio'] * max(cnt['prior6_avg'], 0.5))
            conf_ok = len(callers_w) >= CFG['min_callers'] or (len(tierA_w) >= 1 and spike)
            # narrative-led path: coin is a top-2 leader of a NEW/RISING/HOT narrative whose X keyword count is spiking,
            # and at least 2 organic (non-paid) feeds list the coin
            lead = [d for d in narrs if d['leader_rank'] and d['leader_rank'] <= 2 and d['status'] in ('NEW', 'RISING', 'HOT') and d['x_spike']]
            narr_ok = bool(lead) and len(organic_feeds) >= 2
            sig_type = 'caller' if conf_ok else ('narrative' if narr_ok else None)
            if conf_ok or not narr_ok:
                (passes if conf_ok else fails).append(f"{len(callers_w)} independent tracked caller(s) in last {CFG['caller_window_h']}h: {', '.join(callers_w) or '-'}" + (' (1 tier-A + strong X spike)' if conf_ok and len(callers_w) < CFG['min_callers'] else '')
                                                      + ('' if conf_ok else f"; narrative path not met (needs top-2 leader of a rising narrative with X spike + 2 organic feeds; has {len(organic_feeds)} feeds)"))
            else:
                passes.append(f"narrative-led: top-{lead[0]['leader_rank']} coin of {lead[0]['status']} narrative '{lead[0]['narrative']}' (X keyword spike); organic feeds: {', '.join(organic_feeds)}")
            ca_ok = bool(cnt and cnt['last1'] >= CFG['min_mentions_1h'] and cnt['last1'] >= CFG['min_velocity_ratio'] * max(cnt['prior6_avg'], 0.5) and cnt['last1'] >= 0.5 * cnt['peak'])
            if ca_ok or (cnt and not narr_ok):
                (passes if ca_ok else fails).append(f"X mentions last full hour {cnt['last1']} vs prior-6h avg {cnt['prior6_avg']:.1f}/h (72h peak {cnt['peak']}/h)")
            elif narr_ok: passes.append('narrative starting: X keyword velocity spike stands in for CA mentions' + (f" (CA itself: {cnt['last1']}/h)" if cnt else ''))
            else: fails.append('no X mention-count data this run')
            sh = c.execute('select max(n_authors), max(sample_url) from shill where (key=? or key=?) and ts>=?', (m, '$' + (sym or '').upper(), iso(T - dt.timedelta(hours=48)))).fetchone()
            if sh and sh[0]: fails.append(f'coordinated copy-paste shilling: {sh[0]} accounts posted near-identical text ({sh[1]})')
            if organic and organic[0] == 'low': fails.append(f'Jupiter organic score low ({organic[1]:.0f}) - volume looks bot/wash-traded')
            (passes if (liq or 0) >= CFG['min_liq_usd'] else fails).append(f'liquidity {fmt_usd(liq)}')
            (passes if mcap and CFG['min_mcap'] <= mcap <= CFG['max_mcap'] else fails).append(f'mcap {fmt_usd(mcap)}')
            if mult is not None: (passes if mult < CFG['max_mult_from_first_call'] else fails).append(f'{mult:.1f}x since first tracked call')
            h1 = pc.get('h1')
            if h1 is not None: (passes if h1 <= CFG['max_h1_change_pct'] else fails).append(f'1h price change {h1:+.0f}%')
            if age_min is not None: (passes if CFG['min_age_min'] <= age_min <= CFG['max_age_days'] * 1440 else fails).append(f'pair age {age_min/60:.1f}h')
            (passes if s1 == 0 and b1 > 0 or (s1 and b1 / s1 >= CFG['min_buy_sell_ratio']) else fails).append(f'h1 buys {b1} / sells {s1}')
            if rc:
                safe = not rc['mint_auth'] and not rc['freeze_auth'] and not rc['rugged'] and not rc['dangers'] and rc['top10'] <= CFG['max_top10_pct'] and (rc['creator_pct'] or 0) <= CFG['max_creator_pct']
                (passes if safe else fails).append(f"rug checks: mintAuth={'none' if not rc['mint_auth'] else 'SET'}, freeze={'none' if not rc['freeze_auth'] else 'SET'}, top10 non-pool {rc['top10']:.1f}%, creator {rc['creator_pct'] or 0:.1f}%, dangers={rc['dangers'] or 'none'}, insiders={rc['insiders']}")
            else: fails.append('RugCheck unavailable')
            if bonding: passes.append('NOTE: still on pump.fun bonding curve (not graduated) - higher risk')
            if narrs: passes.append('NARRATIVE: ' + '; '.join(f"{d['narrative']} [{d['status']}]" for d in narrs[:3]))
            if (rc or {}).get('warns') and chain_of(m) == 'bsc': passes.append('NOTE (GoPlus warn): ' + ', '.join(rc['warns']))
            if info['flagged_callers']: passes.append('NOTE: also pushed by flagged accounts: ' + ', '.join(info['flagged_callers']))
            # Callout leaderboard is boost-only: a note on an existing path, never a new sig_type or a cleared fail.
            try:
                _lb_note, _ = PFC.boost_note_for_handles(callers_w, snap=lb_snap)
            except Exception:
                _lb_note = None
            if _lb_note:
                passes.append(_lb_note)
            sm = info.get('sm') or {}
            if sm.get('sm_confirmed'):
                passes.append('smart-money confirmed: ' + sm.get('sm_reason', ''))
            if sm.get('kol_buy'):
                passes.append('KOL buy: ' + sm.get('kol_reason', ''))
            conf = sm.get('confidence') or 'standard'
            if conf == 'standard' and sig_type == 'narrative':
                conf = 'narrative (lower)'
            info['confidence'] = conf
            if conf not in ('standard',):
                passes.append('confidence: ' + conf)
            info['passes'], info['fails'] = passes, fails
            if not fails:
                decision = 'BUY'; info['sig_type'] = sig_type
                c.execute("update coins set status='active', signal_time=?, signal_price=?, signal_liq=?, signal_creator_bal=?, peak_price_since_signal=? where mint=?",
                          (iso(T), price, liq, (rc or {}).get('creator_bal'), price, m))
                buys.append(info)
            elif (len(callers_w) >= 1 and len(fails) <= 2) or (len(fails) == 1 and not callers_w):
                decision = 'WATCH'; watch.append(info)
            else:
                decision = 'REJECT'; rejects.append((m, f"{sym} mcap {fmt_usd(mcap)} liq {fmt_usd(liq)}", fails))
            reasons = fails
        c.execute('insert into snapshots values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (m, iso(T), a.run, price, mcap, liq, vol_h1, vol_h6, b1, s1, (rc or {}).get('holders'),
                   (cnt or {}).get('last1'), (cnt or {}).get('prior6_avg'), decision, json.dumps(reasons)))
    c.commit()
    write_report(rd, a.run, T, buys, watch, holds, sells, rejects, c, board, nlist, sm_bundle.get('status') or {})

def coin_block(i, extra):
    rc = i.get('rc') or {}
    nar = ', '.join(f"{d['narrative']} [{d['status']}]" for d in (i.get('narrs') or [])[:3]) or 'none detected'
    title = f"### ${i['sym']} ({i['name']}) - {i.get('chain', 'solana').upper()}"
    if i.get('sig_type'): title += f" - {i['sig_type']}-led"
    if i.get('confidence') and i['confidence'] not in ('standard',):
        title += f" - {i['confidence']}"
    lines = [title]
    passed = [str(e)[8:].strip() for e in (extra or []) if str(e).startswith('PASSED:')]
    if passed:
        lines.append(f"- In plain English: a BUY on {i['name']} (${i['sym']}) because {'; '.join(passed)}. Not financial advice.")
    lines += [f"- Narrative: {nar}",
             f"- CA: `{i['mint']}`", f"- Chart: {i['url']}",
             f"- Price {i['price']} | mcap {fmt_usd(i['mcap'])} | liq {fmt_usd(i['liq'])} | vol 1h {fmt_usd(i['vol_h1'])} | 1h buys/sells {i['b1']}/{i['s1']} | holders {rc.get('holders','n/a')} | dex {','.join(i['dexes']) or 'n/a'}",
             f"- Callers (all time in DB): {', '.join(i['callers_all'])}; first tracked call: {i['first_call']}"]
    sm = i.get('sm') or {}
    if sm.get('sm_confirmed'): lines.append('- smart-money confirmed: ' + sm.get('sm_reason', ''))
    if sm.get('kol_buy'): lines.append('- KOL buy: ' + sm.get('kol_reason', ''))
    if sm.get('sm_sell') or sm.get('kol_sell'): lines.append('- smart-money/KOL selling: ' + sm.get('sell_reason', ''))
    for k in extra: lines.append(f'- {k}')
    return '\n'.join(lines)

def write_report(rd, run, T, buys, watch, holds, sells, rejects, c, board=(), nlist=(), sm_status=None):
    ct = T.astimezone(dt.timezone(dt.timedelta(hours=-6)))
    out = [f"# Memecoin narrative tracker - run {run}", f"Generated {ct:%Y-%m-%d %H:%M} CST (UTC-6). Signals are rule outputs, not financial advice. Nothing was bought or posted.", '']
    out.append('## Data sources (Helius / GMGN)')
    out += ['- ' + line for line in SM.status_lines(sm_status or {})]
    if sm_status:
        out.append(f"- helius source: {sm_status.get('helius_source') or 'n/a'}; credits: {sm_status.get('helius_credits', 0)}; calls this run: {sm_status.get('helius_calls', 0)}; gmgn calls: {sm_status.get('gmgn_calls', 0)}; wallets: {sm_status.get('helius_wallets_queried', 0)}.")
    out.append('')
    out.append(f"## BUY signals ({len(buys)})")
    out += [coin_block(i, ['PASSED: ' + p for p in i['passes']]) for i in buys] or ['None this run.']
    out.append(f"\n## SELL signals ({len(sells)})")
    out += [coin_block(i, ['WHY: ' + r for r in i['reasons']]) for i in sells] or ['None this run.']
    out.append(f"\n## Active (previous BUY) - holding/watching ({len(holds)})")
    out += [coin_block(i, ['status: ' + r for r in i['reasons']]) for i in holds] or ['None.']
    out.append(f"\n## WATCH - close but not a BUY ({len(watch)})")
    out += [coin_block(i, ['ok: ' + p for p in i['passes']] + ['MISSING: ' + f for f in i['fails']]) for i in watch] or ['None.']
    out.append('\n## Narratives right now (narratives.py; status uses history in state.db + X keyword counts)')
    if nlist:
        out.append('| # | Narrative | status | score | tokens | 1h vol | X posts last hr / prior-6h avg | leaders (1h vol) | why |')
        out.append('|---|---|---|---|---|---|---|---|---|')
        for k, n in enumerate(nlist[:15], 1):
            x = n.get('x'); xs = f"{x['last1']} / {x['prior6_avg']}" if x else '-'
            ld = ', '.join(f"{l['symbol']} ({l['chain'][:3]}, {fmt_usd(l['vol_h1'])})" for l in n['leaders'][:3])
            flag = ' (wash-suspect)' if n.get('wash_suspect') else ''
            out.append(f"| {k} | {n['narrative']}{flag} | {n['status']} | {n['score']} | {n['n_tokens']} | {fmt_usd(n['vol_h1'])} | {xs} | {ld} | {'; '.join(n['why'])[:160]} |")
    else: out.append('narratives.json missing - run `.venv/bin/python narratives.py collect --run RUN`.')
    out += catalyst_section(c, rd, T)
    out.append('\n## Coin momentum board (every coin scored this run)')
    out.append('| Coin | chain | narrative | mcap | liq | X posts last hr | prior-6h avg/hr | peak/hr (72h) | trend | tracked callers (6h) | organic | SM 1h | KOL 1h | rug summary |')
    out.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for i in board:
        k = i['cnt']; rc = i['rc'] or {}
        if k:
            pk = max(k['peak'], 1)
            if k['last3_avg'] <= 0.4 * pk and k['last1'] < 0.5 * pk: trend = 'FADING (%.0f%% below peak)' % (100 * (1 - k['last3_avg'] / pk))
            elif k['last1'] >= 2 * max(k['prior6_avg'], 0.5) and k['last1'] >= 5: trend = 'RISING'
            else: trend = 'FLAT'
            cols = (k['last1'], f"{k['prior6_avg']:.1f}", k['peak'], trend)
        else: cols = ('n/a', 'n/a', 'n/a', 'no data')
        rug = (f"mint {'SET' if rc.get('mint_auth') else 'none'}, freeze {'SET' if rc.get('freeze_auth') else 'none'}, top10 {rc.get('top10', 0):.0f}%, creator {(rc.get('creator_pct') or 0):.1f}%, holders {rc.get('holders')}, dangers {len(rc.get('dangers') or [])}") if rc else 'n/a'
        nar = (i.get('narrs') or [{}])[0].get('narrative', '-') if i.get('narrs') else '-'
        orgl = (i.get('organic') or ('-',))[0] or '-'
        sm = i.get('sm') or {}
        smc = 'confirmed' if sm.get('sm_confirmed') else ('sell' if sm.get('sm_sell') else '-')
        kolc = 'buy' if sm.get('kol_buy') else ('sell' if sm.get('kol_sell') else '-')
        out.append(f"| [${i['sym']}]({i['url']}) | {i.get('chain','solana')} | {nar} | {fmt_usd(i['mcap'])} | {fmt_usd(i['liq'])} | {cols[0]} | {cols[1]} | {cols[2]} | {cols[3]} | {len(i['callers_w'])} | {orgl} | {smc} | {kolc} | {rug} |")
    out.append(f"\n## Rejected ({len(rejects)})")
    for m, s, f in rejects: out.append(f"- {s or '?'} `{m}`: {'; '.join(f)[:300]}")
    _, tiers, _ = load_callers()
    tk = c.execute('select ticker, group_concat(distinct username) from tickers where created_at>=? group by ticker', (iso(T - dt.timedelta(hours=24)),)).fetchall()
    tracked = [(t, [u for u in us.split(',') if u.lower() in tiers]) for t, us in tk]
    tracked = sorted([(t, u) for t, u in tracked if u], key=lambda x: -len(x[1]))[:15]
    out.append('\n## Tickers named by tracked callers in last 24h (resolved to a CA when >=2 callers or 1 tier-A)')
    out += [f'- ${t}: {len(u)} caller(s) ({", ".join(u)})' for t, u in tracked] or ['None.']
    other = sorted([(t, [u for u in us.split(',') if u.lower() not in tiers]) for t, us in tk], key=lambda x: -len(x[1]))
    other = [(t, u) for t, u in other if u][:10]
    if other:
        out.append('\n## Tickers from the Chinese keyword search (untracked accounts - context only, never a signal)')
        out += [f'- ${t}: {len(u)} account(s)' for t, u in other]
    rt = c.execute('select ticker, mint, chain, note from ticker_resolved where ts>=?', (iso(T - dt.timedelta(hours=24)),)).fetchall()
    if rt:
        out.append('\n## Tickers resolved to a CA (highest-volume match; copycats possible)')
        out += [f'- ${t} -> `{m}` ({ch}; {n})' for t, m, ch, n in rt]
    try:
        cp = json.load(open(os.path.join(rd, 'counts_plan.json')))
        out.append(f"\n_X calls this run: {cp.get('search_calls_used')} search + {len(cp.get('queries', []))} counts (budget {cp.get('x_budget')})._")
    except Exception: pass
    open(os.path.join(rd, 'report.md'), 'w').write('\n'.join(out) + '\n')
    print('\n'.join(out))

def catalyst_section(c, rd, T):
    """CZ / He Yi / Binance Square posts in the last 24h whose words match a BSC/Solana token name seen in the feeds."""
    j, _, _ = load_callers()
    cats = [h.lower() for h in catalyst_handles(j)]
    if not cats: return []
    posts = c.execute('select username, created_at, text, url from posts where lower(username) in (%s) and created_at>=?' % ','.join('?' * len(cats)),
                      cats + [iso(T - dt.timedelta(hours=24))]).fetchall()
    out = [f'\n## Chinese catalysts (CZ / He Yi / Binance Square head) - {len(posts)} posts in last 24h']
    try: toks = json.load(open(os.path.join(rd, 'feed_tokens.json')))
    except Exception: toks = []
    hits = {}
    for u, ts, text, url in posts:
        low = (text or '').lower()
        for t in toks:
            nm = (t.get('name') or '').strip(); sym = (t.get('symbol') or '').strip()
            for k in {nm, sym}:
                if not k: continue
                cjk = bool(NARR.CJK_RE.search(k))
                if (cjk and len(k) >= 2 and k in (text or '')) or (not cjk and len(k) >= 5 and k.lower() not in NARR.STOP and re.search(r'\b' + re.escape(k.lower()) + r'\b', low)):
                    key = (url, k)
                    if key not in hits or (t.get('liq') or 0) > (hits[key][1].get('liq') or 0): hits[key] = (u, t, ts)
                    break
    lines = [f"- @{u} {ts[:16]}Z said \"{k}\" -> best-liquidity token {t.get('symbol')} ({t['chain']}, liq {fmt_usd(t.get('liq'))}, 1h vol {fmt_usd(t.get('vol_h1'))}) {url}" for (url, k), (u, t, ts) in hits.items()]
    out += sorted(lines)[:12] or ['No catalyst word matched a live token this run.']
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest='cmd', required=True)
    p1 = sp.add_parser('plan'); p1.add_argument('--run'); p1.add_argument('--lookback-h', type=int, default=24); p1.add_argument('--max-pages', type=int, default=2)
    p1.add_argument('--no-zh', action='store_true', help='skip the Chinese catalyst + keyword searches')
    p2 = sp.add_parser('extract'); p2.add_argument('--run', required=True); p2.add_argument('--max-counts', type=int, default=5); p2.add_argument('--discover', type=int, default=2, help='max GeckoTerminal trending coins to add (0=off)')
    p2.add_argument('--x-budget', type=int, default=20, help='hard cap on X calls per run (searches + counts)')
    p2.add_argument('--narrative-counts', type=int, default=4); p2.add_argument('--narrative-leaders-from', type=int, default=6)
    p2.add_argument('--no-resolve-tickers', dest='resolve_tickers', action='store_false')
    p3 = sp.add_parser('score'); p3.add_argument('--run', required=True)
    a = ap.parse_args()
    {'plan': cmd_plan, 'extract': cmd_extract, 'score': cmd_score}[a.cmd](a)
