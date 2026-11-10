import os
import json,sqlite3,time,urllib.request,concurrent.futures as cf,random,threading,sys
EP=["https://solana-rpc.publicnode.com","https://api.mainnet-beta.solana.com"]
NOW=int(time.time()); CUT=NOW-4*86400
w=[x for x in json.load(open(os.environ.get('SMS_WALLETS','data/smart_wallets.json')))['wallets'] if x.get('stream')]
db=sqlite3.connect('bt.db',check_same_thread=False); L=threading.Lock()
db.execute("create table if not exists sigs(sig text primary key, wallet text, ts int, err int)")
db.execute("create table if not exists wdone(wallet text primary key, n int, capped int)")
done={r[0] for r in db.execute("select wallet from wdone")}
def rpc(m,p):
    for i in range(8):
        u=EP[i%2] if i>1 else EP[0]
        try:
            r=urllib.request.urlopen(urllib.request.Request(u,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),{"content-type":"application/json","User-Agent":"curl/8.5.0"}),timeout=30)
            d=json.loads(r.read())
            if 'result' in d: return d['result']
        except Exception as e: pass
        time.sleep(1+i*2*random.random())
    return None
def crawl(a):
    before=None; n=0; capped=0
    for page in range(6):
        p={"limit":1000}; 
        if before: p["before"]=before
        r=rpc("getSignaturesForAddress",[a,p])
        if not r: break
        rows=[(s['signature'],a,s.get('blockTime') or 0,1 if s.get('err') else 0) for s in r if (s.get('blockTime') or 0)>=CUT]
        with L: db.executemany("insert or ignore into sigs values(?,?,?,?)",rows); db.commit()
        n+=len(rows)
        if len(r)<1000 or (r[-1].get('blockTime') or 0)<CUT: break
        before=r[-1]['signature']
    else: capped=1
    with L: db.execute("insert or replace into wdone values(?,?,?)",(a,n,capped)); db.commit()
    return n
with cf.ThreadPoolExecutor(6) as ex:
    for i,n in enumerate(ex.map(crawl,[x['address'] for x in w if x['address'] not in done])):
        if i%50==0: print(i,n,flush=True)
print("done")
