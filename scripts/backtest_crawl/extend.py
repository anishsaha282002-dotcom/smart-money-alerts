import os
import json,sqlite3,time,urllib.request,concurrent.futures as cf,random,threading,sys
EP="https://api.mainnet-beta.solana.com"; H={"content-type":"application/json","User-Agent":"curl/8.5.0"}
CUT2=int(sys.argv[1]); EDGE=1794156000
db=sqlite3.connect('bt.db',check_same_thread=False); L=threading.Lock()
def rpc(m,p):
    for i in range(10):
        try:
            d=json.loads(urllib.request.urlopen(urllib.request.Request(EP,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),H),timeout=30).read())
            if 'result' in d: return d['result']
        except Exception: pass
        time.sleep(1+i*random.random()*2)
    return None
book=[x for x in json.load(open(os.environ.get('SMS_WALLETS','data/smart_wallets.json')))['wallets'] if x.get('stream')]
capped={r[0] for r in db.execute("select wallet from wdone where capped=1")}
db.execute("create table if not exists wext(wallet text primary key, n int)")
done={r[0] for r in db.execute("select wallet from wext")}
def crawl(a):
    r=db.execute("select sig,ts from sigs where wallet=? and ts>0 order by ts limit 1",(a,)).fetchone()
    before=r[0] if r and r[1]<EDGE+3600 else None
    if r and r[1]>=EDGE+3600: before=None
    n=0
    for page in range(4):
        p={"limit":1000}
        if before: p["before"]=before
        res=rpc("getSignaturesForAddress",[a,p])
        if not res: break
        rows=[(s['signature'],a,s.get('blockTime') or 0,1 if s.get('err') else 0) for s in res if CUT2<=(s.get('blockTime') or 0)<EDGE+3600]
        with L: db.executemany("insert or ignore into sigs values(?,?,?,?)",rows); db.commit()
        n+=len(rows)
        if len(res)<1000 or (res[-1].get('blockTime') or 0)<CUT2: break
        before=res[-1]['signature']
    with L: db.execute("insert or replace into wext values(?,?)",(a,n)); db.commit()
ws=[x['address'] for x in book if x['address'] not in capped and x['address'] not in done]
with cf.ThreadPoolExecutor(3) as ex:
    for i,_ in enumerate(ex.map(crawl,ws)):
        if i%50==0: print('sig',i,flush=True)
print('sigs ext done',flush=True)
