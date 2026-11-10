#!/usr/bin/env python3
"""Export the latest run as compact JSON for the dashboard Page (Memecoin Narrative Tracker).
Usage: python3 dashboard_data.py [--run RUN] > runs/RUN/dashboard.json
The agent then pastes the JSON over the `const DATA = {...};` line of the Page with EditCanvas (see README)."""
import json, os, sqlite3, glob, argparse, statistics, datetime as dt, sys
import tracker as T

ap = argparse.ArgumentParser(); ap.add_argument('--run'); ap.add_argument('--tsx', action='store_true', help='print the Page DATA block (between // DATA:START and // DATA:END)'); a = ap.parse_args()
runs = sorted((d for d in os.listdir(T.RUNS) if os.path.exists(os.path.join(T.RUNS, d, 'narratives.json')) and os.path.exists(os.path.join(T.RUNS, d, 'report.md'))), key=lambda d: os.path.getmtime(os.path.join(T.RUNS, d, 'report.md')))
run = a.run or runs[-1]; rd = os.path.join(T.RUNS, run)
c = sqlite3.connect(T.DB)
ts = c.execute('select max(ts) from snapshots where run=?', (run,)).fetchone()[0]
cst = (dt.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=-6))).strftime('%a %b %-d, %Y %-I:%M %p CST')) if ts else None

try:
    smj = json.load(open(os.path.join(rd, 'smartmoney.json')))
except Exception:
    smj = {}
sm_by = smj.get('by_mint') or {}
sm_status = smj.get('status') or {}

def sm_for(mint):
    return sm_by.get(mint) or sm_by.get(T.norm(mint)) or {}

# signals
sig = [dict(zip(('mint', 'sym', 'decision', 'reasons'), r)) for r in c.execute(
    "select s.mint, k.symbol, s.decision, s.reasons from snapshots s join coins k on k.mint=s.mint where s.run=? and s.decision in ('BUY','SELL')", (run,))]
for x in sig:
    s = sm_for(x['mint'])
    x['smConfirmed'] = bool(s.get('sm_confirmed'))
    x['kolBuy'] = bool(s.get('kol_buy'))
    x['smSell'] = bool(s.get('sm_sell') or s.get('kol_sell'))
    x['confidence'] = s.get('confidence') or 'standard'
    x['smReason'] = s.get('sm_reason') or s.get('kol_reason') or s.get('sell_reason') or ''

# narratives
nj = json.load(open(os.path.join(rd, 'narratives.json')))
hist = {r[0]: r[1:] for r in c.execute('select narrative, status, x_last1, x_prior6, x_peak from narrative_hist where run=?', (run,))}
narr = []
for n in nj['narratives'][:20]:
    h = hist.get(n['narrative'], (None, None, None, None))
    narr.append({'name': n['narrative'], 'chains': '/'.join(k for k, _ in sorted(n['chains'].items(), key=lambda x: -x[1])),
                 'status': h[0] or 'n/a', 'score': n['score'], 'tokens': n['n_tokens'], 'vol1h': n['vol_h1'],
                 'x1h': h[1], 'x6h': h[2], 'xpeak': h[3], 'wash': bool(n.get('wash_suspect')),
                 'leaders': [{'sym': (l['symbol'] or '?').strip(), 'chain': l['chain'], 'mcap': l['mcap']} for l in n['leaders'][:3]]})

# watched coins (scored this run)
coins = []
for m, price, mcap, liq, dec, reasons in c.execute('select mint, price, mcap, liq, decision, reasons from snapshots where run=? and ts=?', (run, ts)):
    k = c.execute('select symbol, chain, first_call_url from coins where mint=?', (m,)).fetchone() or ('?', None, '')
    hi = c.execute('select max(price), count(distinct run) from snapshots where mint=? and price is not null', (m,)).fetchone()
    cnt = T.load_counts(rd, m)
    callers6 = c.execute("select count(distinct lower(username)) from mentions where mint=? and flagged=0 and tier in ('A','B') and created_at>=?",
                         (m, T.iso(dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) - dt.timedelta(hours=6)))).fetchone()[0]
    rs = json.loads(reasons or '[]')
    rug = next((r for r in rs if r.startswith('rug checks')), None)
    s = sm_for(m)
    coins.append({'sym': (k[0] or '?').strip(), 'chain': k[1] or T.chain_of(m), 'ca': m,
                  'url': f"https://dexscreener.com/{k[1] or T.chain_of(m)}/{m}", 'mcap': mcap, 'liq': liq,
                  'pxVsHigh': round((price / hi[0] - 1) * 100, 1) if price and hi[0] else None, 'runsSeen': hi[1],
                  'xVsPeak': round((cnt['last1'] / cnt['peak'] - 1) * 100) if cnt and cnt['peak'] else None,
                  'callers6h': callers6, 'decision': dec, 'source': k[2],
                  'rug': 'unavailable' if not rug and any('RugCheck unavailable' in r for r in rs) else ('fail: ' + rug[12:] if rug else 'pass'),
                  'blockers': [r for r in rs if not r.startswith('rug checks')][:4],
                  'smConfirmed': bool(s.get('sm_confirmed')),
                  'kolBuy': bool(s.get('kol_buy')),
                  'smSell': bool(s.get('sm_sell') or s.get('kol_sell')),
                  'confidence': s.get('confidence') or 'standard',
                  'smReason': s.get('sm_reason') or s.get('kol_reason') or s.get('sell_reason') or ''})

# callers
j = json.load(open(os.path.join(T.HERE, 'callers.json')))
callers = []
for x in j['callers']:
    note = x.get('note', '')
    grp = 'Chinese' if x.get('lang') == 'zh' else ('Followed' if 'you follow' in note else 'External')
    callers.append({'handle': x['handle'], 'group': grp, 'tier': x['tier'], 'note': note})
for x in j['flagged']: callers.append({'handle': x['handle'], 'group': 'Flagged', 'tier': 'flagged', 'note': x['why']})
for x in j.get('catalysts', []): callers.append({'handle': x['handle'], 'group': 'Catalyst', 'tier': 'catalyst', 'note': x['note']})

# backtest
bt = json.load(open(os.path.join(T.HERE, 'backtest', 'backtest_results.json')))
ok = [b for b in bt if b.get('entry')]
bts = {'calls': len(bt), 'priced': len(ok),
       'hit2x': sum(1 for b in ok if (b.get('peak72') or 0) >= 2), 'medianPeak': round(statistics.median([b['peak72'] for b in ok]), 2) if ok else None,
       'medianNow': round(statistics.median([b['now'] for b in ok]), 2) if ok else None,
       'medianRules': round(statistics.median([b['rules'] for b in ok]), 2) if ok else None,
       'rulesWin': sum(1 for b in ok if (b.get('rules') or 0) > 1),
       'rows': [{'who': b['who'], 'sym': b['sym'], 't': b['t'][:10], 'peak': b.get('peak72'), 'now': b.get('now'), 'rules': b.get('rules'), 'exit': b.get('exit'), 'note': b.get('note', '')} for b in ok]}
cp = json.load(open(os.path.join(rd, 'counts_plan.json')))
if a.tsx:
    J = lambda o: json.dumps(o, ensure_ascii=False)
    def src(x):
        x = x or ''
        if x.startswith('https://x.com/'): return x.split('/')[3] + ' call'
        return x.replace(' (no caller yet)', '')
    out = ['// DATA:START (refreshed from dashboard_data.py)',
           f"const RUN = {{ id: {J(run)}, lastRun: {J(cst)}, buys: {sum(1 for x in sig if x['decision']=='BUY')}, sells: {sum(1 for x in sig if x['decision']=='SELL')}, xSearch: {cp.get('search_calls_used') or 0}, xCounts: {len(cp.get('queries', []))}, xBudget: {cp.get('x_budget') or 20}, helius: {J(sm_status.get('helius') or 'n/a')}, heliusSource: {J(sm_status.get('helius_source') or 'n/a')}, gmgn: {J(sm_status.get('gmgn') or 'n/a')} }};",
           'const NARR: Narr[] = [']
    for n in narr[:15]:
        out.append('  ' + J({k: n[k] for k in ('name','chains','status','score','tokens','vol1h','x1h','x6h','xpeak','wash')} | {'leaders': [{'sym': l['sym'], 'chain': l['chain'], 'mcap': round(l['mcap'] or 0)} for l in n['leaders']]}) + ',')
    out.append('];'); out.append('const COINS: Coin[] = [')
    for k in coins:
        out.append('  ' + J({'sym': k['sym'], 'chain': k['chain'], 'ca': k['ca'], 'mcap': round(k['mcap'] or 0), 'liq': round(k['liq'] or 0), 'pxVsHigh': k['pxVsHigh'],
                             'runsSeen': k['runsSeen'], 'xVsPeak': k['xVsPeak'], 'callers6h': k['callers6h'], 'source': src(k['source']), 'rug': k['rug'] if k['rug'] in ('pass','unavailable') else 'fail',
                             'blockers': [b.split(';')[0][:80] for b in k['blockers']][:3],
                             'smConfirmed': k['smConfirmed'], 'kolBuy': k['kolBuy'], 'smSell': k['smSell'],
                             'confidence': k['confidence']}) + ',')
    out.append('];'); out.append('// DATA:END')
    print('\n'.join(out)); sys.exit(0)
print(json.dumps({'run': run, 'lastRun': cst, 'signals': sig, 'narratives': narr, 'coins': coins, 'callers': callers, 'backtest': bts,
                  'xCalls': {'search': cp.get('search_calls_used'), 'counts': len(cp.get('queries', [])), 'budget': cp.get('x_budget')},
                  'smartmoney': {'helius': sm_status.get('helius'), 'gmgn': sm_status.get('gmgn'),
                                 'heliusCalls': sm_status.get('helius_calls'), 'heliusSource': sm_status.get('helius_source'), 'gmgnCalls': sm_status.get('gmgn_calls')},
                  'feeds': nj.get('feed_status')}, ensure_ascii=False, separators=(',', ':')))
