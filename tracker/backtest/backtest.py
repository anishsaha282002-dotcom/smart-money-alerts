"""Rough back-test: 'what if you bought when a tracked caller posted the call on X'.
Prices: GeckoTerminal hourly OHLCV of the token's top pool. Entry = close of the hour candle containing the X post
(approximation; real fills would be worse). Exits simulated with the tracker's price rules: stop-loss -35%,
take half at 2x, trailing stop -30% from peak once up 30%+, else mark-to-market now. Sample is tiny and hand-collected."""
import json, time, urllib.request, datetime as dt, sys
sys.path.insert(0, '..')
UA={'User-Agent':'Mozilla/5.0'}
def get(u):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(15); continue
            return None
        except Exception: time.sleep(3)
CALLS=[
 ('mickeymantled','9X5UwHT7gWSPtAH5yeEzrLHqv3Nedmhy3HyZN3Yspump','2026-11-03T08:02:27Z','https://x.com/mickeymantled/status/2117527812987134459',''),
 ('MemeRetire','GYG9ezuhhUzq4p68K4a2phhHW9qZqTXaPimgp8NWpump','2026-11-03T20:45:15Z','https://x.com/MemeRetire/status/2117719781193191747','X post says "$SEXBOT 5x" - posted AFTER the run'),
 ('Chairman_DN','EwX2T1p2PmgTsSq2Bi6XtQYxPC5krR4P2fxPfN4Qpump','2026-11-03T16:04:36Z','https://x.com/Chairman_DN/status/2117649151345541481','re-share of a ~16-day-old callout'),
 ('mickeymantled','6i3oFRo48Xbnu7B9YH5DgypHRvsr47GagoJhSvs4pump','2026-11-04T04:14:48Z','https://x.com/mickeymantled/status/2117832913618370951',''),
 ('MemeRetire','GWWtfWBqZpAQaC5E6qaBeP88dPGBRpjCzP22Q4Yvpump','2026-11-04T16:57:18Z','https://x.com/MemeRetire/status/2118024800564289988','$WendyQuest'),
 ('MemeRetire','H8WTvo3ZXSYHJAcYqzCforbG8coR1FDAX2kHFfqHBAGS','2026-11-05T05:45:18Z','https://x.com/MemeRetire/status/2118218076550291849','$BAGSPAY'),
 ('ProofOfEly','AjZ8JFAvMAdrRFG4yfuozGBnpEM4DKPg1JV5nuNqpump','2026-11-05T15:35:47Z','https://x.com/ProofOfEly/status/2118366675057954958','his own coin (fees to PauseAI) - self-promotion'),
 ('ProofOfEly','98HEU4TvXB3xjB1t15fgxHwYDLUH4fDomvp2DCzJpump','2026-11-06T00:49:37Z','https://x.com/ProofOfEly/status/2118506050806591906','$LEEROY'),
 ('mickeymantled','5wSQpQfbdSKs7amvyxa2XTzWXNyionERZWdDWykYm1At','2026-11-07T03:35:11Z','https://x.com/mickeymantled/status/2118910104594764242','his own project (souvenir) migration'),
 ('Dior100x','6mXFCoZ515w37YfmwXGJMPfQfiK5tr9WkihW3oN9pump','2026-11-08T09:45:03Z','https://x.com/Dior100x/status/2119365573402599453','$PIRATE'),
]
rows=[]
for who,mint,t,url,note in CALLS:
    tok=get(f'https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}?include=top_pools'); time.sleep(2.5)
    if not tok or not tok.get('data'): rows.append(dict(who=who,mint=mint,t=t,url=url,note=note,err='no gecko data')); continue
    a=tok['data']['attributes']; sym=a.get('symbol')
    pools=tok['data'].get('relationships',{}).get('top_pools',{}).get('data',[])
    if not pools: rows.append(dict(who=who,mint=mint,sym=sym,t=t,url=url,note=note,err='no pool')); continue
    pool=pools[0]['id'].replace('solana_','')
    o=get(f'https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/hour?aggregate=1&limit=300&currency=usd&token=base'); time.sleep(2.5)
    c=sorted((o or {}).get('data',{}).get('attributes',{}).get('ohlcv_list',[]))
    ts=int(dt.datetime.fromisoformat(t.replace('Z','+00:00')).timestamp())
    after=[x for x in c if x[0]>=ts-3600]
    if not after: rows.append(dict(who=who,mint=mint,sym=sym,t=t,url=url,note=note,err='no candles around call (pool may be newer/older than window)')); continue
    entry=after[0][4]
    w72=[x for x in after if x[0]<=ts+72*3600]
    peak72=max(x[2] for x in w72)/entry
    now=c[-1][4]/entry
    # simulate exits
    peak=1.0; half=False; realized=0; pos=1.0; exit_reason='still held -> mark to market'
    for x in after[1:]:
        hi,lo,cl=x[2]/entry,x[3]/entry,x[4]/entry
        if not half and hi>=2.0: realized+=0.5*2.0; pos=0.5; half=True
        peak=max(peak,hi)
        if lo<=0.65 and peak<1.3: realized+=pos*0.65; pos=0; exit_reason='stop-loss -35%'; break
        if peak>=1.3 and lo<=peak*0.7: realized+=pos*peak*0.7; pos=0; exit_reason=f'trailing stop after peak {peak:.2f}x'; break
    if pos: realized+=pos*now
    rows.append(dict(who=who,mint=mint,sym=sym,t=t,url=url,note=note,entry=entry,peak72=round(peak72,2),now=round(now,2),rules=round(realized,2),exit=exit_reason,candles=len(c)))
json.dump(rows,open('backtest_results.json','w'),indent=1)
for r in rows: print(r)
