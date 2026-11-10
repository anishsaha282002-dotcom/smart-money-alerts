import os
"""Free price history for signal mints: DexScreener (pair lookup) + GeckoTerminal 5-min OHLCV (30 req/min)."""
import json,sqlite3,time,urllib.request,sys
UA={'User-Agent':'Mozilla/5.0','accept':'application/json'}
db=sqlite3.connect('prices.db',timeout=60)
db.execute("create table if not exists pools(mint text primary key, pool text, dex text, created int, liq real, fdv real, src text)")
db.execute("create table if not exists ohlcv(mint text, ts int, o real, h real, l real, c real, v real, primary key(mint,ts))")
db.execute("create table if not exists ohlcv_done(mint text primary key, n int, t0 int)")
def get(u, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(20); continue
            if e.code==404: return None
            time.sleep(3)
        except Exception: time.sleep(3)
    return None
# mints to price: >=2 distinct tracked wallets bought, or any kol-tagged buy; plus first buy time
targets=json.load(open('targets.json'))   # {mint: t0}
have={r[0] for r in db.execute("select mint from pools")}
need=[m for m in targets if m not in have]
for i in range(0,len(need),30):
    chunk=need[i:i+30]
    d=get("https://api.dexscreener.com/tokens/v1/solana/"+",".join(chunk)) or []
    best={}
    for p in d:
        m=p['baseToken']['address']
        if m not in chunk: continue
        liq=(p.get('liquidity') or {}).get('usd') or 0
        if m not in best or liq>best[m][3]: best[m]=(p['pairAddress'],p.get('dexId'),int((p.get('pairCreatedAt') or 0)/1000),liq,p.get('fdv'))
    for m in chunk:
        b=best.get(m)
        db.execute("insert or replace into pools values(?,?,?,?,?,?,?)",(m,)+(b if b else (None,None,None,None,None))+('dexscreener' if b else 'none',))
    db.commit(); time.sleep(0.3)
print("pools", db.execute("select count(*), sum(pool is not null) from pools").fetchone(), flush=True)
# GT fallback for no-pool mints
for (m,) in db.execute("select mint from pools where pool is null").fetchall():
    d=get(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{m}/pools?page=1")
    time.sleep(2.1)
    ps=(d or {}).get('data') or []
    if ps:
        a=ps[0]['attributes']; pid=ps[0]['id'].split('_',1)[1]
        db.execute("update pools set pool=?,dex=?,src='geckoterminal',liq=? where mint=?",(pid,ps[0]['relationships']['dex']['data']['id'],float(a.get('reserve_in_usd') or 0),m)); db.commit()
print("pools after GT", db.execute("select count(*), sum(pool is not null) from pools").fetchone(), flush=True)
done={r[0] for r in db.execute("select mint from ohlcv_done")}
todo=[(m,p) for m,p in db.execute("select mint,pool from pools where pool is not null") if m not in done]
print("ohlcv todo",len(todo),flush=True)
for j,(m,p) in enumerate(todo):
    t0=int(targets[m]); before=min(int(time.time()), t0+1000*300-600)
    d=get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{p}/ohlcv/minute?aggregate=5&limit=1000&currency=usd&token={m}&before_timestamp={before}")
    rows=((d or {}).get('data') or {}).get('attributes',{}).get('ohlcv_list') or []
    db.executemany("insert or ignore into ohlcv values(?,?,?,?,?,?,?)",[(m,int(r[0]),r[1],r[2],r[3],r[4],r[5]) for r in rows])
    db.execute("insert or replace into ohlcv_done values(?,?,?)",(m,len(rows),t0)); db.commit()
    if j%25==0: print(j,len(rows),flush=True)
    time.sleep(2.05)
print("done")
