# Strategy: 1 imaginary SOL → 10 SOL (paper only)

**Imaginary money. This app never trades and never holds a wallet.** The strategy below runs as a
paper account on the live alerts (`sms paper`), recorded in `record/paper.jsonl` with the same
hash chain as the public record, so every loss stays visible.

---

## 1. The honest starting point

Odds from the backtest (`python scripts/paper_odds.py`): 20,000 simulated runs, each starting at
1 SOL, 15% of the bankroll per trade, the exits in section 4, ~4% costs per round trip.

| Signal | Alerts in backtest | Average per trade | Reached 10 SOL | Went broke |
|---|---|---|---|---|
| One tracked wallet buys | 75 | **−18%** | 0% | ~100% |
| 2+ wallets within 1h | 226 | **−17%** | 0% | ~100% |
| 3+ wallets within 1h | 128 | **−18%** | 0% | ~100% |
| 5+ wallets within 30m | 26 | −2% | ~2% | ~50% |
| 3+ wallets within 6h **and** a Pump.fun callout-leader wallet | 25 | **+11%** | ~71% | ~0% |

**What this means:**

- Copying smart-money buys on their own **loses money**, even in clusters. Most of these coins fall
  50% within a day.
- Only one signal came out positive. **It rests on 25 alerts from 3 days, with wallets chosen using
  hindsight.** That is far too little to trust; real odds are almost certainly worse.
- This is why the paper run comes first. It is the only way to find out without losing anything.

## 2. Where the narrative comes from (what is actually possible for free)

| Source | Use now? | How |
|---|---|---|
| DexScreener, GeckoTerminal, Jupiter trending | **Yes** | Already in the app. The narrative board compares the last hour with the last day |
| CoinGecko meme categories | **Yes** | Already in the app: 24h change of AI, Chinese, animal, political memes |
| Pump.fun callout leaderboard | **Yes** | Already in the app; the strongest signal in the table above |
| Telegram public channels | **Yes** | Reader already built (`t.me/s/<channel>`) |
| GMGN call-outs | Yes, with the free key | Replaces X for caller tracking |
| X / Twitter | Only on a paid API tier | Without it, check the coin's X by hand before acting |
| Reddit | Maybe | Free API is non-commercial and new keys may need manual approval |
| TikTok, Douyin, Xiaohongshu, Weibo | **No** | No free API; scraping breaks their terms. Check by hand, or skip |

So the automated narrative filter is **trending-list momentum** (new / rising / hot), not post counts
from every platform. The 10x dream usually needs the wider social wave; this filter only sees its
on-chain echo.

## 3. Entry rules (all must pass)

1. A tracked wallet graded **A or B** buys.
2. **3 or more** graded wallets bought the same coin (single buys and pairs lost money).
3. The coin's narrative is **new, rising or hot**, not fading.
4. The buying wallet **still holds at least 90%** at alert time. (In the live record so far, most
   wallets had already sold before the alert arrived. This rule skips those.)
5. Market cap **under $3M** (room to 10x), liquidity **at least $20K** (room to get out).
6. No honeypot, sell-tax or rug warning.
7. The alert is less than 2 hours old.

## 4. Size and exits

| Rule | Setting | Why |
|---|---|---|
| Size | **15% of the bankroll** per trade | 10x needs compounding; any bigger and two stop-outs end the run |
| Max open | 3 positions | Most cash stays safe while waiting |
| Stop loss | Sell everything at **−35%** | Most losers fall 50%+ within a day |
| Take profit | Sell **half at 2x** | Locks the stake back and more |
| Let it run | The rest exits **30% below its highest price**, or all at **6x** | The few big winners pay for everything |
| Time limit | Sell what's left after **24h** | Memecoin moves are mostly over by then |
| Costs | 3% slippage each way + 1% fee each side | Real fills are worse than chart prices |

## 5. How to read the paper run

```bash
sms paper
```

It prints the imaginary balance, open positions, closed trades, wins, best and worst trade. The
same numbers go to the website data. Skipped alerts are recorded with the reason.

**Judge it after at least 30 closed trades**, not after one lucky week. If it is below 1 SOL after
30 trades, the strategy does not work, and the rules change in the open, in a new paper file.

## 6. Live record so far (13 Nov 2026)

The 7 real buy alerts in the record would all have been **skipped**:

| Alert | Coin | Reason |
|---|---|---|
| a-00001 | CatFu | only 1 wallet |
| a-00002 | Dacity | only 1 wallet |
| a-00003 | Dacity | only 1 wallet |
| a-00004 | Dacity | wallet already sold 100% |
| a-00005 | CATE | narrative steady |
| a-00006 | ANSEM | only 1 wallet |
| a-00007 | mihao | only 1 wallet |

A strategy that waits is still a strategy. The paper account stays at 1 SOL until a real cluster
alert arrives.

---

*Not financial advice. Imaginary money only. Memecoins are extremely risky and most go to zero.*
