import json,sqlite3,time,urllib.request,concurrent.futures as cf,random,threading,sys
import os
EP=os.environ.get("EP","https://solana-rpc.publicnode.com")
H={"content-type":"application/json","User-Agent":"curl/8.5.0"}
Q={"So11111111111111111111111111111111111111112":"SOL","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":"USDC","Es9vMFrzaCERmJfrF8H5zN2rL1CqHUm6qzRQLWMYJNYb":"USDT"}
db=sqlite3.connect('bt.db',check_same_thread=False); L=threading.Lock()
db.execute("create table if not exists swaps(sig text, wallet text, mint text, side text, tok real, sol real, usd_q real, ts int, primary key(sig,wallet,mint))")
db.execute("create table if not exists txdone(sig text primary key, ok int)")
todo=[r for r in db.execute("select s.sig,s.wallet,s.ts from sigs s join wdone w using(wallet) where s.err=0 and w.capped=0 and s.ts<"+os.environ.get('MAXTS','9999999999')+" and s.sig not in (select sig from txdone where ok=1)")]
print("todo",len(todo),flush=True)
def rpc(m,p):
    for i in range(6):
        try:
            d=json.loads(urllib.request.urlopen(urllib.request.Request(EP,json.dumps({"jsonrpc":"2.0","id":1,"method":m,"params":p}).encode(),H),timeout=30).read())
            if 'result' in d: return d['result'],True
        except Exception as e: pass
        time.sleep(0.5+i*random.random()*2)
    return None,False
def parse(tx,wallet):
    m=tx.get('meta') or {}
    keys=[k['pubkey'] if isinstance(k,dict) else k for k in tx['transaction']['message']['accountKeys']]
    sol=0.0
    if wallet in keys:
        i=keys.index(wallet); sol=(m['postBalances'][i]-m['preBalances'][i])/1e9
    d={}
    for side,arr in ((-1,m.get('preTokenBalances') or []),(1,m.get('postTokenBalances') or [])):
        for b in arr:
            if b.get('owner')!=wallet: continue
            v=float(b['uiTokenAmount'].get('uiAmountString') or 0)
            d[b['mint']]=d.get(b['mint'],0)+side*v
    q=0.0
    for mint,sym in Q.items():
        if mint in d:
            if sym=="SOL": sol+=d.pop(mint)
            else: q+=d.pop(mint)
    out=[]
    for mint,v in d.items():
        if abs(v)<=0: continue
        if v>0 and (sol<-0.001 or q<-0.5): out.append((mint,'buy',v,-sol,-q))
        elif v<0 and (sol>0.001 or q>0.5): out.append((mint,'sell',-v,sol,q))
    return out
def work(r):
    sig,wallet,ts=r
    tx,ok=rpc("getTransaction",[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":1}])
    rows=[]
    if tx:
        try: rows=[(sig,wallet,mi,s,tk,so,qq,tx.get('blockTime') or ts) for mi,s,tk,so,qq in parse(tx,wallet)]
        except Exception: pass
    with L:
        db.executemany("insert or ignore into swaps values(?,?,?,?,?,?,?,?)",rows)
        db.execute("insert or replace into txdone values(?,?)",(sig,1 if tx else 0))
    return 1
n=0;t0=time.time()
with cf.ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv)>1 else 12) as ex:
    for _ in ex.map(work,todo):
        n+=1
        if n%1000==0:
            with L: db.commit()
            print(n, round(n/(time.time()-t0),1),"rps",flush=True)
db.commit(); print("done")
