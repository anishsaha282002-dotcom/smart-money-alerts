#!/usr/bin/env python3
"""
Narrative layer for the memecoin tracker (research/signals only - never trades, never posts).

`collect --run RUN` pulls free, keyless feeds that are keyless, clusters every token it sees into
narratives (seed synonym map + emergent keywords, English and Chinese), scores them, and writes
runs/RUN/narratives.json, which includes the X count queries for the top narratives.
`tracker.py extract` adds those queries to the run's budgeted counts_plan.json, and `tracker.py score`
calls `finalize()` to fold in X keyword velocity, compare against history in state.db, and label each
narrative NEW / RISING / HOT / FLAT / FADING.

Feeds (all free, no key, tested on 2026-11-09):
  DexScreener  /metas/trending/v1 + /metas/meta/v1/<slug>  (DexScreener's own narrative 'metas' with mcap change)
               /token-boosts/latest/v1, /token-boosts/top/v1 (PAID promos - counted as weak/paid signal only)
               /token-profiles/latest/v1, /community-takeovers/latest/v1, /tokens/v1/<chain>/<addrs> (enrichment)
  GeckoTerminal trending_pools (solana, bsc), solana new_pools, bsc four-meme dex pools
  Jupiter      lite-api.jup.ag/tokens/v2/toptrending/1h (has organicScore = wash-trading filter)
  PumpPortal   wss://pumpportal.fun/api/data subscribeNewToken + subscribeMigration (N-second snapshot)
  Binance      Alpha token list (bapi public) - Chinese-named BSC memes that Binance Alpha listed
  CoinGecko    /search/trending (coins + categories)
Not reachable without a browser (Cloudflare/WAF): pump.fun frontend API, gmgn.ai, four.meme API, Binance Square.
"""
import argparse, asyncio, json, os, re, sqlite3, sys, time, math, datetime as dt
import urllib.request, urllib.error
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, 'runs')
DB = os.path.join(HERE, 'state.db')
UA = {'User-Agent': 'Mozilla/5.0 (memecoin-tracker research)'}
CHAINS = ('solana', 'bsc')
ORGANIC = {'gecko_trending', 'gecko_new', 'gecko_fourmeme', 'jup_trending', 'ds_meta', 'pumpportal_new',
           'pumpportal_migration', 'binance_alpha', 'ds_cto', 'cg_trending'}
PAID = {'ds_boost_latest', 'ds_boost_top', 'ds_profile'}   # projects pay DexScreener for these

def now(): return dt.datetime.now(dt.timezone.utc)
def iso(t): return t.strftime('%Y-%m-%dT%H:%M:%SZ')

def http_json(url, data=None, tries=2, timeout=25):
    for i in range(tries):
        try:
            h = dict(UA)
            if data is not None: h['Content-Type'] = 'application/json'
            req = urllib.request.Request(url, headers=h, data=json.dumps(data).encode() if data is not None else None)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(6 * (i + 1)); continue
            return None
        except Exception:
            time.sleep(1.5)
    return None

# ---------------- seed narrative map (English + Chinese keywords) ----------------
SEED = {
    'dogs':              ['dog', 'doge', 'shib', 'inu', 'puppy', 'pup', 'wif', 'bonk', 'shiba', '狗', '犬', '柴犬'],
    'cats':              ['cat', 'kitty', 'meow', 'popcat', 'mew', 'kitten', '猫', '喵', '哈基米', 'hakimi'],
    'frogs/pepe':        ['pepe', 'frog', 'toad', '青蛙', '蛙', '佩佩'],
    'other animals':     ['penguin', 'monkey', 'ape', 'bear', 'hippo', 'moodeng', 'goat', 'fish', 'duck', 'pig', 'rabbit', 'panda',
                          'capybara', 'otter', '企鹅', '猴', '熊', '猪', '兔', '熊猫', '鸭', '龙虾', 'lobster'],
    'AI/agents':         ['ai', 'agent', 'agents', 'gpt', 'grok', 'claude', 'openai', 'llm', 'bot', 'x402', 'neural', 'robot', 'agi', '智能', '机器人', 'gemini'],
    'Trump/politics':    ['trump', 'maga', 'melania', 'barron', 'vance', 'potus', 'election', 'president', '川普', '特朗普', '懂王'],
    'Elon/X/SpaceX':     ['elon', 'musk', 'tesla', 'spacex', 'xai', 'xmoney', 'starship', 'mars', 'spcx', '马斯克'],
    'Binance/CZ/BNB':    ['cz', 'binance', 'bnb', 'heyi', 'giggle', 'safu', 'yzi', '币安', '何一', '客服', '赵长鹏', '大表哥', '广场', '币安人生'],
    'Chinese-culture':   ['修仙', '人生', '牛逼', '牛', '马', '马年', '龙', '福', '发财', '财神', '躺平', '老子', '黑马', '雪球', '我踏马来了', '红包',
                          'kungfu', 'dragon', 'chinese', 'china', 'xiuxian'],
    'gaming/GTA':        ['gta', 'game', 'gaming', 'nintendo', 'pokemon', 'tcg', 'minecraft', 'roblox', 'playstation', 'xbox', 'steam'],
    'tiktok/brainrot':   ['tiktok', 'brainrot', 'skibidi', 'rizz', 'sigma', 'gyatt', 'tralalero', 'italian', 'aura', 'mog', 'npc'],
    'celebrity/streamer':['kanye', 'drake', 'ishowspeed', 'speed', 'mrbeast', 'kai', 'cenat', 'taylor', 'swift', 'celebrity'],
    'money/wealth':      ['money', 'rich', 'wealth', 'millionaire', 'billion', 'gold', 'dollar', 'cash', 'bank', '钱', '富'],
    'sports':            ['nba', 'nfl', 'football', 'soccer', 'messi', 'ronaldo', 'fifa', 'worldcup', 'olympic', 'ufc'],
    'religion/spiritual':['jesus', 'god', 'buddha', 'bible', 'church', 'pray', '佛'],
    'wojak/chad':        ['wojak', 'gigachad', 'troll', 'cope', 'pepe2'],
}
STOP = set('''the and for with coin token official of on in to a an is it my you this that sol solana pump fun pumpfun bsc bnb chain
new by from at be are was it's its your our we me us all just no not yes get go up out one two inu x com io www http https t co
token's v2 v3 2 3 inc finance protocol dao labs ai16z wrapped usd usdt usdc sui eth btc'''.split())
# 'inu','bnb','sol' already covered above; keep them out of emergent keywords
CJK_STOP = set('的了是在不一我你他她它这那有个人们来去上下大小中也和就都要会说还又被吧啊呢吗么币')
CJK_RE = re.compile(r'[\u4e00-\u9fff]+')
WORD_RE = re.compile(r'[a-z][a-z0-9]{2,}')

def kw_of(text):
    """Return (latin words, cjk tokens) for clustering."""
    t = (text or '').lower()
    words = {w for w in WORD_RE.findall(t) if w not in STOP}
    cjk = set()
    for run in CJK_RE.findall(text or ''):
        if len(run) <= 6: cjk.add(run)
        for i in range(len(run)):
            if run[i] not in CJK_STOP: cjk.add(run[i])
            if i + 1 < len(run): cjk.add(run[i:i + 2])
    return words, cjk

SEED_INDEX = {}
for n, kws in SEED.items():
    for k in kws: SEED_INDEX.setdefault(k.lower(), set()).add(n)

def seed_match(words, cjk, sym):
    hits = set()
    sym_l = (sym or '').lower()
    for w in words | {sym_l}:
        if w in SEED_INDEX: hits |= SEED_INDEX[w]
        else:
            # substring match for latin seeds >= 4 chars inside a word or ticker (e.g. 'pepecoin', 'catwif')
            for k, ns in SEED_INDEX.items():
                if len(k) >= 4 and k.isascii() and k in w: hits |= ns
    for c in cjk:
        if c in SEED_INDEX: hits |= SEED_INDEX[c]
    return hits

# ---------------- feeds ----------------
def add_tok(store, chain, addr, src, **kw):
    if not addr or chain not in CHAINS: return
    key = (chain, addr if chain == 'solana' else addr.lower())
    t = store.setdefault(key, {'chain': chain, 'address': addr, 'sources': set(), 'metas': set(), 'name': None, 'symbol': None, 'desc': ''})
    t['sources'].add(src)
    for k, v in kw.items():
        if v is None or v == '': continue
        if k == 'meta': t['metas'].add(v)
        elif k == 'desc': t['desc'] = (t['desc'] + ' ' + v)[:400]
        elif t.get(k) in (None, '', 0): t[k] = v

def from_pair(store, p, src, meta=None):
    bt = p.get('baseToken') or {}
    add_tok(store, p.get('chainId'), bt.get('address'), src, name=bt.get('name'), symbol=bt.get('symbol'), meta=meta,
            vol_h1=(p.get('volume') or {}).get('h1'), vol_h24=(p.get('volume') or {}).get('h24'),
            mcap=p.get('marketCap') or p.get('fdv'), liq=(p.get('liquidity') or {}).get('usd'),
            pc_h1=(p.get('priceChange') or {}).get('h1'), created=p.get('pairCreatedAt'), dex=p.get('dexId'),
            buys_h1=((p.get('txns') or {}).get('h1') or {}).get('buys'), sells_h1=((p.get('txns') or {}).get('h1') or {}).get('sells'),
            url=p.get('url'))

def feed_dexscreener(store, status, max_metas=8):
    metas = http_json('https://api.dexscreener.com/metas/trending/v1') or []
    status['ds_metas'] = len(metas)
    meta_rows = []
    for m in metas:
        mc = m.get('marketCapChange') or {}
        meta_rows.append({'slug': m['slug'], 'name': m['name'], 'mcap': m.get('marketCap'), 'volume': m.get('volume'),
                          'tokens': m.get('tokenCount'), 'chg_h1': mc.get('h1'), 'chg_h6': mc.get('h6'), 'chg_h24': mc.get('h24')})
    # fetch pairs for the metas moving most in the last hour, always including 'chinese'
    pick = sorted(meta_rows, key=lambda r: -(r['chg_h1'] or -99))[:max_metas]
    if not any(r['slug'] == 'chinese' for r in pick): pick.append({'slug': 'chinese'})
    for r in pick:
        d = http_json(f"https://api.dexscreener.com/metas/meta/v1/{r['slug']}") or {}
        for p in d.get('pairs') or []: from_pair(store, p, 'ds_meta', meta=r['slug'])
        time.sleep(0.4)
    for url, src in [('https://api.dexscreener.com/token-boosts/latest/v1', 'ds_boost_latest'),
                     ('https://api.dexscreener.com/token-boosts/top/v1', 'ds_boost_top'),
                     ('https://api.dexscreener.com/token-profiles/latest/v1', 'ds_profile'),
                     ('https://api.dexscreener.com/community-takeovers/latest/v1', 'ds_cto')]:
        d = http_json(url) or []
        status[src] = len(d)
        for x in d: add_tok(store, x.get('chainId'), x.get('tokenAddress'), src, desc=x.get('description'), url=x.get('url'))
        time.sleep(0.3)
    return meta_rows

def feed_gecko(store, status):
    urls = [('https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?duration=1h', 'gecko_trending', 'solana'),
            ('https://api.geckoterminal.com/api/v2/networks/bsc/trending_pools?duration=1h', 'gecko_trending', 'bsc'),
            ('https://api.geckoterminal.com/api/v2/networks/solana/new_pools', 'gecko_new', 'solana'),
            ('https://api.geckoterminal.com/api/v2/networks/bsc/dexes/four-meme/pools?sort=h24_volume_usd_desc', 'gecko_fourmeme', 'bsc')]
    for url, src, chain in urls:
        d = http_json(url) or {}
        rows = d.get('data') or []
        status[f'{src}_{chain}'] = len(rows)
        for pool in rows:
            a = pool.get('attributes') or {}
            base = ((pool.get('relationships') or {}).get('base_token') or {}).get('data', {}).get('id', '')
            addr = base.split('_', 1)[1] if '_' in base else None
            nm = (a.get('name') or '').split(' / ')[0]
            tx = (a.get('transactions') or {}).get('h1') or {}
            created = a.get('pool_created_at')
            add_tok(store, chain, addr, src, name=nm, symbol=nm, vol_h1=float((a.get('volume_usd') or {}).get('h1') or 0),
                    vol_h24=float((a.get('volume_usd') or {}).get('h24') or 0), mcap=float(a.get('market_cap_usd') or a.get('fdv_usd') or 0) or None,
                    liq=float(a.get('reserve_in_usd') or 0), pc_h1=float((a.get('price_change_percentage') or {}).get('h1') or 0),
                    buys_h1=tx.get('buys'), sells_h1=tx.get('sells'),
                    created=int(dt.datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp() * 1000) if created else None)
        time.sleep(2.2)  # GeckoTerminal free tier ~30 req/min

def feed_jupiter(store, status):
    d = http_json('https://lite-api.jup.ag/tokens/v2/toptrending/1h?limit=50') or []
    status['jup_trending'] = len(d)
    for x in d:
        s1 = x.get('stats1h') or {}
        add_tok(store, 'solana', x.get('id'), 'jup_trending', name=x.get('name'), symbol=x.get('symbol'), mcap=x.get('mcap'),
                liq=x.get('liquidity'), vol_h1=(s1.get('buyVolume') or 0) + (s1.get('sellVolume') or 0),
                organic_vol_h1=(s1.get('buyOrganicVolume') or 0) + (s1.get('sellOrganicVolume') or 0),
                organic_label=x.get('organicScoreLabel'), organic_score=x.get('organicScore'), launchpad=x.get('launchpad'))

def feed_binance_alpha(store, status, days=21):
    d = http_json('https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list') or {}
    rows = d.get('data') or []
    status['binance_alpha_total'] = len(rows)
    cutoff = (now() - dt.timedelta(days=days)).timestamp() * 1000
    n = 0
    for x in rows:
        if x.get('chainId') != '56': continue
        is_zh = bool(CJK_RE.search((x.get('symbol') or '') + (x.get('name') or '')))
        if not is_zh and (x.get('listingTime') or 0) < cutoff: continue
        n += 1
        add_tok(store, 'bsc', x.get('contractAddress'), 'binance_alpha', name=x.get('name'), symbol=x.get('symbol'),
                mcap=float(x.get('marketCap') or 0) or None, vol_h24=float(x.get('volume24h') or 0), alpha_listed=x.get('listingTime'),
                alpha_chg24=float(x.get('percentChange24h') or 0))
    status['binance_alpha_used'] = n

def feed_coingecko(status):
    d = http_json('https://api.coingecko.com/api/v3/search/trending') or {}
    status['cg_trending'] = len(d.get('coins') or [])
    return {'coins': [c['item'].get('symbol') for c in d.get('coins') or []],
            'categories': [c.get('name') for c in d.get('categories') or []]}

async def _pumpportal(seconds):
    import websockets
    out = {'new': [], 'migrations': []}
    try:
        async with websockets.connect('wss://pumpportal.fun/api/data', open_timeout=15, ping_interval=20) as ws:
            await ws.send(json.dumps({'method': 'subscribeNewToken'}))
            await ws.send(json.dumps({'method': 'subscribeMigration'}))
            t0 = time.time()
            while time.time() - t0 < seconds:
                try: m = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError: continue
                try: j = json.loads(m)
                except Exception: continue
                if j.get('txType') == 'create': out['new'].append({k: j.get(k) for k in ('mint', 'name', 'symbol', 'marketCapSol', 'pool')})
                elif j.get('txType') == 'migrate' or 'migrat' in json.dumps(j)[:200].lower() and j.get('mint'):
                    out['migrations'].append({k: j.get(k) for k in ('mint', 'name', 'symbol', 'pool', 'txType')})
    except Exception as e:
        out['error'] = repr(e)[:200]
    return out

def feed_pumpportal(store, status, seconds):
    try:
        res = asyncio.run(_pumpportal(seconds))
    except ImportError:
        status['pumpportal'] = 'websockets not installed (use .venv/bin/python)'; return {'new': [], 'migrations': []}
    status['pumpportal_new'] = len(res['new']); status['pumpportal_migrations'] = len(res['migrations'])
    if res.get('error'): status['pumpportal_error'] = res['error']
    for x in res['new']: add_tok(store, 'solana', x['mint'], 'pumpportal_new', name=x.get('name'), symbol=x.get('symbol'))
    for x in res['migrations']: add_tok(store, 'solana', x['mint'], 'pumpportal_migration', name=x.get('name'), symbol=x.get('symbol'))
    return res

def enrich(store, status, cap=150):
    """Fill missing market data with DexScreener /tokens/v1 (30 addresses per call)."""
    for chain in CHAINS:
        need = [t['address'] for t in store.values() if t['chain'] == chain and t.get('vol_h1') is None and t.get('liq') in (None, 0)]
        need = need[:cap]
        for i in range(0, len(need), 30):
            d = http_json(f"https://api.dexscreener.com/tokens/v1/{chain}/" + ','.join(need[i:i + 30])) or []
            best = {}
            for p in d:
                a = (p.get('baseToken') or {}).get('address')
                if a and ((p.get('liquidity') or {}).get('usd') or 0) >= ((best.get(a, {}).get('liquidity') or {}).get('usd') or 0): best[a] = p
            for p in best.values(): from_pair(store, p, 'ds_enrich')
            time.sleep(0.35)
    for t in store.values(): t['sources'].discard('ds_enrich')

# ---------------- clustering + scoring ----------------
NON_MEME = re.compile(r'(backpack|xstock|securities|tokeni[sz]ed|wrapped|bridged|staked|liquid staking|treasury|\bETF\b|ondo|usd\b)', re.I)
STOCK_TICKERS = set('NVDA NVDAX AMD AAPL TSLA TSLAX SPY QQQ SQQQ TQQQ MSFT GOOGL AMZN META COIN MSTR HOOD SKHY CRCL PLTR SPCX'.split())
def is_meme(t):
    nm = f"{t.get('name') or ''} {t.get('symbol') or ''} {t.get('desc') or ''}"
    if NON_MEME.search(nm): return False
    if (t.get('symbol') or '').upper().lstrip('$') in STOCK_TICKERS: return False
    if (t.get('mcap') or 0) > 1.5e9: return False      # majors / blue chips are not narrative plays
    return True

def cluster(store, pp):
    narr = defaultdict(lambda: {'tokens': [], 'keywords': Counter()})
    emergent = defaultdict(set); kw_tokens = defaultdict(list)
    for k in [k for k, t in store.items() if not is_meme(t)]: store.pop(k)
    for key, t in store.items():
        words, cjk = kw_of(f"{t.get('name') or ''} {t.get('symbol') or ''}")
        dwords, dcjk = kw_of(t.get('desc') or '')
        hits = seed_match(words, cjk, t.get('symbol'))
        if not hits: hits = seed_match(dwords, dcjk, None)
        if CJK_RE.search((t.get('name') or '') + (t.get('symbol') or '')): hits.add('Chinese-culture') if not hits & {'Binance/CZ/BNB'} else None
        for m in t['metas']:
            hits.add('ds:' + m)
        t['narratives'] = sorted(hits)
        for h in hits: narr[h]['tokens'].append(key)
        for h in hits:
            for w in words | cjk:
                if w in SEED_INDEX and h in SEED_INDEX[w]: narr[h]['keywords'][w] += 1
        for w in words | {c for c in cjk if len(c) >= 2}:
            emergent[w].add(key); kw_tokens[w].append(key)
    # emergent keywords: >=3 distinct tokens, not a seed keyword, not covered by a seed narrative already for most tokens
    for w, keys in emergent.items():
        if len(keys) < 3 or w in SEED_INDEX or w in STOP or (w.isascii() and len(w) < 3) or w.isdigit(): continue
        name = 'kw:' + w
        narr[name]['keywords'][w] += len(keys)
        for k in keys:
            narr[name]['tokens'].append(k); store[k].setdefault('narratives', [])
            if name not in store[k]['narratives']: store[k]['narratives'].append(name)
    return narr

def fnum(x):
    try: return float(x or 0)
    except Exception: return 0.0

def score_narratives(store, narr, meta_rows):
    meta_by = {m['slug']: m for m in meta_rows}
    out = []
    for name, d in narr.items():
        toks = [store[k] for k in dict.fromkeys(d['tokens'])]
        if len(toks) < 2 and not name.startswith('ds:'): continue
        srcs = Counter(s for t in toks for s in t['sources'])
        organic_feeds = {s for s in srcs if s in ORGANIC}
        vol_h1 = sum(fnum(t.get('vol_h1')) for t in toks); vol_h24 = sum(fnum(t.get('vol_h24')) for t in toks)
        launches = sum(1 for t in toks if 'pumpportal_new' in t['sources'])
        migrations = sum(1 for t in toks if 'pumpportal_migration' in t['sources'])
        young = sum(1 for t in toks if t.get('created') and (time.time() * 1000 - t['created']) < 48 * 3600 * 1000)
        pcs = sorted(fnum(t.get('pc_h1')) for t in toks if t.get('pc_h1') is not None)
        med_pc = pcs[len(pcs) // 2] if pcs else 0.0
        chains = Counter(t['chain'] for t in toks)
        meta = meta_by.get(name[3:]) if name.startswith('ds:') else None
        # momentum score (heuristic, documented in README): breadth + fresh launches + 1h volume + price + young tokens
        score = (math.log10(1 + vol_h1) * 2 + len(organic_feeds) * 1.5 + min(len(toks), 30) * 0.3 + launches * 1.5 + migrations * 3
                 + young * 0.5 + max(min(med_pc, 200), -50) / 25 + (fnum((meta or {}).get('chg_h1')) / 2 if meta else 0))
        leaders = sorted([t for t in toks if (t.get('liq') or 0) >= 5000], key=lambda t: -fnum(t.get('vol_h1')))[:4]
        out.append({'narrative': name, 'score': round(score, 2), 'n_tokens': len(toks), 'organic_feeds': sorted(organic_feeds),
                    'paid_promo_tokens': sum(1 for t in toks if t['sources'] & PAID), 'vol_h1': round(vol_h1), 'vol_h24': round(vol_h24),
                    'median_pc_h1': round(med_pc, 1), 'new_launches_sample': launches, 'migrations_sample': migrations, 'young_48h': young,
                    'chains': dict(chains), 'ds_meta': meta,
                    'leaders': [{'chain': t['chain'], 'address': t['address'], 'symbol': t.get('symbol'), 'name': t.get('name'),
                                 'vol_h1': round(fnum(t.get('vol_h1'))), 'liq': round(fnum(t.get('liq'))), 'mcap': round(fnum(t.get('mcap'))),
                                 'pc_h1': t.get('pc_h1'), 'organic_label': t.get('organic_label'), 'feeds': sorted(t['sources']),
                                 'age_h': round((time.time() * 1000 - t['created']) / 3.6e6, 1) if t.get('created') else None}
                                for t in leaders],
                    'wash_suspect': bool(leaders) and all(l.get('organic_label') == 'low' for l in leaders if l.get('organic_label')) and any(l.get('organic_label') for l in leaders),
                    'sample_tokens': [t.get('symbol') or t.get('name') for t in toks[:12]]})
    out.sort(key=lambda r: -r['score'])
    sets = {r['narrative']: set(dict.fromkeys(narr[r['narrative']]['tokens'])) for r in out}
    kept = []
    for r in out:
        dup = None
        for k in kept:
            a, b = sets[r['narrative']], sets[k['narrative']]
            if a and b and len(a & b) / len(a | b) >= 0.6: dup = k; break
        if dup: dup.setdefault('aliases', []).append(r['narrative'])
        else: kept.append(r)
    for r in kept: r['top_keywords'] = [w for w, _ in narr[r['narrative']]['keywords'].most_common(4)]
    return kept

def x_query_for(n):
    terms = []
    for l in n['leaders'][:3]:
        sym = (l.get('symbol') or '').strip().lstrip('$')
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9]{1,11}', sym): terms.append('$' + sym)
        elif CJK_RE.fullmatch(sym or ''): terms.append(sym)
    kws = n.get('top_keywords') or ([n['narrative'][3:].replace('-', ' ')] if n['narrative'][:3] in ('kw:', 'ds:') else [])
    for k in kws:
        if len(terms) >= 6: break
        if k.isascii() and len(k) < 3: continue
        if len(k) == 1: continue                      # single CJK chars are far too broad on X
        k = f'"{k}"' if ' ' in k or '-' in k else k
        if k not in terms and '$' + k.upper() not in [t.upper() for t in terms]: terms.append(k)
    if not terms: terms = [n['narrative'].split(':')[-1].replace('-', ' ')]
    zh = [bool(CJK_RE.search(t)) for t in terms]
    if all(zh): ctx = '(meme OR 土狗 OR 金狗 OR bsc OR 币安 OR CA OR 冲)'
    elif any(zh): ctx = '(memecoin OR meme OR solana OR pumpfun OR bsc OR CA OR 土狗 OR 币安)'
    else: ctx = '(memecoin OR meme OR solana OR pumpfun OR bsc OR CA OR ape)'
    return f"({' OR '.join(dict.fromkeys(terms))}) {ctx} -is:retweet"

def slug(name): return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '_', name).strip('_')[:40] or 'n'

def cmd_collect(a):
    rd = os.path.join(RUNS, a.run); os.makedirs(rd, exist_ok=True)
    store, status = {}, {}
    t0 = time.time()
    meta_rows = feed_dexscreener(store, status)
    feed_gecko(store, status)
    feed_jupiter(store, status)
    feed_binance_alpha(store, status)
    cg = feed_coingecko(status)
    pp = feed_pumpportal(store, status, a.ws_seconds) if a.ws_seconds > 0 else {'new': [], 'migrations': []}
    enrich(store, status)
    narr = cluster(store, pp)
    ranked = score_narratives(store, narr, meta_rows)
    # X keyword-velocity queries for the top narratives (excluding pure DexScreener-meta duplicates of seeds)
    xq = []
    for n in ranked:
        if len(xq) >= a.x_narratives: break
        if n['narrative'] in ('wojak/chad',) or n['vol_h1'] < 5000: continue
        xq.append({'tool': 'x.get_posts_counts_recent', 'save_as': f"counts_narr_{slug(n['narrative'])}.txt", 'narrative': n['narrative'],
                   'args': {'query': x_query_for(n), 'granularity': 'hour', 'start_time': iso(now() - dt.timedelta(hours=48))}})
    tokens = [{**{k: v for k, v in t.items() if k not in ('sources', 'metas')}, 'sources': sorted(t['sources']), 'metas': sorted(t['metas'])} for t in store.values()]
    out = {'run': a.run, 'generated': iso(now()), 'seconds': round(time.time() - t0), 'feed_status': status,
           'ds_metas': meta_rows, 'coingecko_trending': cg, 'narratives': ranked[:40], 'x_count_queries': xq,
           'pumpportal_sample': {'seconds': a.ws_seconds, 'new': pp['new'][:200], 'migrations': pp['migrations']}}
    json.dump(out, open(os.path.join(rd, 'narratives.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(tokens, open(os.path.join(rd, 'feed_tokens.json'), 'w'), ensure_ascii=False)
    print(json.dumps({'run': a.run, 'tokens_seen': len(store), 'narratives': len(ranked), 'feed_status': status,
                      'top': [(n['narrative'], n['score'], n['n_tokens']) for n in ranked[:12]], 'x_queries': len(xq)}, ensure_ascii=False, indent=1))

# ---------------- finalize (called from tracker.py score) ----------------
def _counts(path):
    try:
        t = open(path, encoding='utf-8').read(); i = t.find('{')
        o, _ = json.JSONDecoder().raw_decode(t[i:])
    except Exception: return None
    b = sorted(o.get('data') or [], key=lambda x: x['start'])
    vals = [x.get('tweet_count', 0) for x in b]
    if len(vals) < 3: return None
    full = vals[:-1]
    last1 = full[-1]; prior6 = full[-7:-1]; p6 = sum(prior6) / len(prior6) if prior6 else 0
    return dict(last1=last1, prior6_avg=round(p6, 1), last3_avg=round(sum(full[-3:]) / 3, 1), peak=max(full), total=sum(vals))

def finalize(rd, c):
    """Merge X velocity + history -> status per narrative. Returns (narratives list, map address->[narrative dicts])."""
    p = os.path.join(rd, 'narratives.json')
    if not os.path.exists(p): return [], {}
    nj = json.load(open(p))
    c.execute('create table if not exists narrative_hist(run text, ts text, narrative text, score real, n_tokens int, vol_h1 real, x_last1 int, x_prior6 real, x_peak int, status text, primary key(run, narrative))')
    xmap = {q['narrative']: _counts(os.path.join(rd, q['save_as'])) for q in nj.get('x_count_queries', [])}
    T = now(); by_addr = defaultdict(list); out = []
    prior_runs = c.execute('select count(distinct run) from narrative_hist where run<>?', (nj['run'],)).fetchone()[0]
    for n in nj['narratives']:
        name = n['narrative']; x = xmap.get(name)
        hist = c.execute('select score, vol_h1, x_last1, ts from narrative_hist where narrative=? and run<>? order by ts desc limit 6', (name, nj['run'])).fetchall()
        peak_vol = max([h[1] or 0 for h in hist] + [n['vol_h1']])
        prev_scores = [h[0] for h in hist[:3]]
        status, why = 'FLAT', []
        x_spike = bool(x and x['last1'] >= 20 and x['last1'] >= 2 * max(x['prior6_avg'], 1))
        x_fading = bool(x and x['peak'] >= 20 and x['last3_avg'] <= 0.4 * x['peak'])
        if not hist:
            if prior_runs: status = 'NEW'; why.append('first time this narrative is on the board')
            else: why.append('baseline (first narrative run - NEW/RISING need history)')
        if prev_scores and n['score'] >= 1.3 * (sum(prev_scores) / len(prev_scores)): status = 'RISING'; why.append('momentum score up >=30% vs last runs')
        if x_spike: status = 'RISING' if status != 'NEW' else 'NEW'; why.append(f"X mentions {x['last1']}/h vs prior-6h avg {x['prior6_avg']}/h")
        if n['new_launches_sample'] >= 2 or n['migrations_sample'] >= 1: why.append(f"{n['new_launches_sample']} new pump.fun launches / {n['migrations_sample']} graduations in sample")
        meta = n.get('ds_meta') or {}
        if fnum(meta.get('chg_h1')) >= 5: why.append(f"DexScreener meta mcap {meta['chg_h1']:+.1f}% 1h")
        vol_fade = bool(hist) and n['vol_h1'] <= 0.5 * peak_vol
        if vol_fade or x_fading or fnum(meta.get('chg_h6')) <= -15:
            why.append('1h volume <=50% of its peak' if vol_fade else (f"X mentions last-3h avg {x['last3_avg']}/h vs 48h peak {x['peak']}/h" if x_fading else f"meta mcap {meta.get('chg_h6'):+.1f}% 6h"))
            # a fresh X spike on top of a faded peak is a second leg / rebound, not a new narrative start
            status = 'REBOUND' if x_spike and not vol_fade else 'FADING'
        if status in ('RISING', 'NEW') and x_spike and len(n['organic_feeds']) >= 3: status = 'HOT'
        n2 = {**n, 'status': status, 'why': why, 'x': x, 'x_spike': x_spike}
        out.append(n2)
        c.execute('insert or replace into narrative_hist values(?,?,?,?,?,?,?,?,?,?)', (nj['run'], iso(T), name, n['score'], n['n_tokens'], n['vol_h1'],
                  (x or {}).get('last1'), (x or {}).get('prior6_avg'), (x or {}).get('peak'), status))
        for l in n['leaders']:
            by_addr[l['address'] if l['chain'] == 'solana' else l['address'].lower()].append({'narrative': name, 'status': status, 'x_spike': x_spike, 'leader_rank': n['leaders'].index(l) + 1})
    c.commit()
    # also tag every feed token with its narratives (non-leaders)
    try:
        for t in json.load(open(os.path.join(rd, 'feed_tokens.json'))):
            k = t['address'] if t['chain'] == 'solana' else t['address'].lower()
            have = {d['narrative'] for d in by_addr.get(k, [])}
            st = {n['narrative']: n for n in out}
            for nm in t.get('narratives', []):
                if nm in st and nm not in have: by_addr[k].append({'narrative': nm, 'status': st[nm]['status'], 'x_spike': st[nm]['x_spike'], 'leader_rank': None})
    except Exception: pass
    return out, by_addr

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('collect'); p.add_argument('--run', required=True); p.add_argument('--ws-seconds', type=int, default=60)
    p.add_argument('--x-narratives', type=int, default=4, help='X count queries for top narratives')
    a = ap.parse_args()
    {'collect': cmd_collect}[a.cmd](a)
