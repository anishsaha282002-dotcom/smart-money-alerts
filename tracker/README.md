# Memecoin narrative tracker (research and signals only)

This tool never trades, posts, likes, follows or DMs. Its signals come from fixed rules and are not financial advice.

## Files
- `following_crypto.csv`: the 437 accounts @DaTa369x follows, classified (`classify_following.py`)
- `callers.json`: tracked callers (tier A/B) plus flagged accounts that are excluded from BUY confluence
- `tracker.py`: plan, extract and score steps; state lives in `state.db` (SQLite)
- `narratives.py`: free-feed collector + narrative clustering/scoring (needs `.venv` for the PumpPortal websocket)
- `smartmoney.py`: read-only Helius + GMGN clients (smart-money / KOL boosters). Never trades or signs.
- `helius_stream.py` / `stream_worker.py`: Free-plan Parsed Streams worker that writes SWAP buys/sells to `helius_swaps.db` (no 12-wallet cap). `stream_worker.pid` / `stream_worker.log` live here.
- `smart_wallets.json`: tracked Solana smart-money wallets (public sources, with a URL and tags per wallet; `kol` tags feed the KOL-buy label)
- `tests/test_smartmoney.py`, `tests/test_helius_stream.py`: parser, stream/dedupe/cluster, and rule tests
- `RESEARCH.md`: existing tools, repos, MCPs, Chinese platforms, paid options (10 Nov 2026)
- `tracker_v2_backup.py`, `dashboard_data_v2_backup.py`, `README_v2_backup.md`, `RESEARCH_v2_backup.md`: pre-Helius/GMGN copies
- `tracker_v1_backup.py`, `callers_v1_backup.json`: pre-v2 copies
- `xparse.py`: parser for saved X API responses
- `callouts_cache.json`: map of pump.fun callout link to mint (pump.fun is Cloudflare-blocked for scripts, so the agent resolves these with WebFetch)
- `runs/<RUN>/`: plan.json, posts_*.txt, counts_plan.json, counts_<mint>.txt, callouts_to_resolve.json, report.md
- `backtest/`: rough back-test (`backtest.py`, `backtest_results.json`)

## One run (v2, 10 Nov 2026). The agent does the X steps, because X is only reachable through MCP
```
cd /workspace/memecoin-tracker
python3 tracker.py plan                                   # prints RUN; writes runs/RUN/plan.json (4 searches: EN callers, ZH callers, catalysts, ZH keywords)
.venv/bin/python narratives.py collect --run RUN          # ~60-90s; free feeds + PumpPortal websocket snapshot -> narratives.json, feed_tokens.json
#   agent: x.search_posts_all with each plan.json query (args exactly as given). Only the callers_en query may take 1 extra page
#          (pagination_token=meta.next_token, save as posts_0_p2.txt). Save raw output as runs/RUN/<save_as>.
python3 tracker.py extract --run RUN                      # shill detection, ticker->CA resolution, narrative leaders, budgeted counts_plan.json
#   agent: WebFetch any pump.fun/c/ links in callouts_to_resolve.json -> add to callouts_cache.json -> re-run extract
#   agent: x.get_posts_counts_recent with each counts_plan.json query (args exactly as given) -> runs/RUN/<save_as>
python3 tracker.py score --run RUN                        # writes runs/RUN/report.md, updates state.db (coins, snapshots, narrative_hist)
```
If `.venv` is missing: `python3 -m venv .venv && .venv/bin/pip install websockets`.
X budget: `extract --x-budget 20` (default) caps searches + count queries at 20 per run. Typical run: 4-5 searches + 10-15 counts.
Every 2h from 8AM to 10PM CST (8 runs) that is at most 160 X reads a day, inside the 1000/day limit.
Count priority when the budget is tight: active BUY positions > coins named by tracked callers (max 5) > top-4 narrative keyword counts > GeckoTerminal trending (max 2) > narrative leaders.

## Sources (all free, no key, tested from this box 9 Nov 2026)
| Feed | Used for |
|---|---|
| DexScreener `/metas/trending/v1`, `/metas/meta/v1/<slug>` | DexScreener's own narrative groups ("metas", e.g. cat, ai, chinese, x402) with mcap change; pairs per meta |
| DexScreener `/token-boosts/latest|top/v1`, `/token-profiles/latest/v1` | paid promotions; shown as "paid", never counted as organic |
| DexScreener `/community-takeovers/latest/v1`, `/tokens/v1/<chain>/...`, `/latest/dex/search` | CTOs, market data (Solana + BSC), ticker->CA resolution |
| GeckoTerminal trending_pools (solana, bsc), solana new_pools, bsc `four-meme` dex pools | organic trending + four.meme coverage |
| Jupiter `lite-api.jup.ag/tokens/v2/toptrending/1h` and `/search` | trending + organicScore (low = bot/wash volume -> BUY blocker) |
| PumpPortal `wss://pumpportal.fun/api/data` (subscribeNewToken, subscribeMigration) | live pump.fun launches/graduations (60s snapshot per run) |
| Binance Alpha token list (bapi public) | Chinese-named BSC memes that Binance Alpha listed |
| CoinGecko `/search/trending` | trending coins + categories |
| RugCheck (Solana), GoPlus `token_security/56` (BSC) | rug / honeypot / tax / holder checks |
Blocked from the box: pump.fun frontend API, gmgn.ai web, four.meme API, Binance Square (Cloudflare/WAF).

## Optional keyed sources (read-only; skipped if the env var is missing)
Set these in the shell before `score`. The tracker never signs up, never reads a private key, and never links a wallet. If a key is absent or a call fails, that source is skipped and the report logs `helius: no key` / `gmgn: no key` (or an error string). Existing BUY/SELL rules still apply.

| Env var | Where to get a free key | What the tracker uses |
|---|---|---|
| `HELIUS_API_KEY` | [Helius dashboard](https://dashboard.helius.dev) — Free plan ($0/mo, no card, 1M credits). Docs: [plans](https://www.helius.dev/docs/billing/plans), [Parsed Streams](https://www.helius.dev/docs/parsed-streams). | **Primary:** `stream_worker.py` opens `parsedTransactionSubscribe` on `wss://beta.helius-rpc.com` (verified on Free; 1 credit/event) and records SWAP buys/sells for every wallet in `smart_wallets.json` into `helius_swaps.db`. The subscribe filter AND's `accounts.include` with nine swap programs (Jupiter, Raydium AMM/CLMM/CPMM, Pump.fun, PumpSwap, Meteora DLMM/pools, Orca) so credits are spent on swap-related txs, not every wallet mention. `transactionSubscribe` is not on Free; `logsSubscribe` is the fallback. **If the worker is not running** (heartbeat older than 2 minutes), `score` polls Parsed Events history (`POST /v1/parsed-events/transaction-history`, ~10 credits/request) — not the legacy 100-credit Enhanced Transactions endpoint. Optional: `stream_worker.py register-webhook --url https://...` (refuses without a public HTTPS URL; the box has no public URL, so no webhook is created by default). |
| `GMGN_API_KEY` | [GMGN Agent API key page](https://gmgn.ai/ai) — upload a locally generated public key ([tutorial](https://docs.gmgn.ai/index/generate-public-key), [Agent API docs](https://docs.gmgn.ai/index/gmgn-agent-api)). Query skills need only the API key, not the private key. IPv4 only. | Official OpenAPI (`https://openapi.gmgn.ai`), exist-auth only (header `X-APIKEY` + `timestamp` + `client_id`). Read endpoints: `GET /v1/user/smartmoney`, `GET /v1/user/kol`, `POST /v1/market/token_signal` (types 12 = smart-money buy, 20 = KOL buy) on `sol`, `bsc`, `base`. A hard guard refuses trade / order / swap / wallet-management / `follow-wallet` commands. The official CLI is not installed here because it also bundles trading. |

`smart_wallets.json` is a **public, dated snapshot** (compiled 9 Nov 2026, America/Chicago), not a live feed. Each wallet has a source URL and a `stats.stats_date`. The seeded ten still come from [Solana Trading, 2 Nov 2026](https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-october-2026); the expanded list also uses committed GitHub snapshots from [nirholas/kol-quest](https://github.com/nirholas/kol-quest) (GMGN scrape 9 Mar 2026; Kolscan leaderboard retrieved 9 Nov 2026), the [Evidence Deflator Kolscan freeze (15 Oct 2026)](https://evidencedeflator.com/data/kolscan/frozen-2026-10-15.json), [duolaAmengweb3 verified KOLs (3 May 2026)](https://github.com/duolaAmengweb3/solana-alpha-tracker/blob/main/packages/core/src/data/verified.json), and a [yksanjo/kol-tracker snapshot (21 May 2026)](https://github.com/yksanjo/kol-tracker). Sniper-only, inactive, and ~200+ swaps/day wallets are excluded from the stream (the latter sit in the same file with `stream: false`). The worker enforces a 30,000-credit daily cap (configurable) and shrinks to the top-ranked subset at 80%. Cielo public pages did not expose full addresses; live gmgn.ai rank endpoints returned 403. Cloning the repo only needs a free `HELIUS_API_KEY`. Add or disable wallets as you like. Leaderboard ranks change quickly; this is not financial advice.

## Helius stream worker
```
cd /workspace/memecoin-tracker
# one-shot check (does not print the API key)
.venv/bin/python stream_worker.py probe
# start (pid: stream_worker.pid, log: stream_worker.log)
nohup .venv/bin/python stream_worker.py run >> stream_worker.log 2>&1 & echo $! > stream_worker.pid
```
`tracker.py score` reads `helius_swaps.db` when the worker heartbeat is fresh, so the scoring routine does not need to open its own WebSocket. If the worker is down, score cheap-polls and the report says `helius: ok (poll fallback)`. Keep the worker running between score runs to stay on the 1-credit/event path.

## Narrative layer (narratives.py)
- Every token from the feeds is clustered by a seed map (dogs, cats, frogs/pepe, AI/agents, Trump, Elon/X, Binance/CZ, Chinese-culture, gaming, brainrot, ...; English + Chinese keywords), DexScreener metas, and emergent keywords (a word or Chinese 2-char term shared by >=3 tokens). Clusters overlapping >=60% are merged.
- Score = log(1h volume) + organic feeds + breadth + new pump.fun launches + graduations + young tokens + median 1h price change + DexScreener meta 1h mcap change.
- The top 4 narratives get an X count query (leaders' tickers + top keywords, with crypto context). Status: NEW (not seen in earlier runs), RISING (score +30% vs last runs, or X keyword count >=20/h and >=2x prior-6h avg), HOT (rising + X spike + >=3 organic feeds), REBOUND (X spike but still far below its 48h peak), FADING (1h volume <=50% of its peak, X last-3h <=40% of its 48h peak, or DexScreener meta -15% in 6h), FLAT. The first run is a baseline.
- `wash-suspect` = every narrative leader has a Jupiter organic score of "low".

## Chinese coverage
- `callers.json` has 22 `lang=zh` callers (tier B: Chinese influence lists, no audited hit rate) plus `catalysts` (cz_binance, heyibinance, yingbinance). Catalyst posts are never counted as calls; the report lists catalyst words that match a live token name.
- A Chinese keyword search (土狗/金狗/打狗/四妹/内盘/外盘/冲了/埋伏/叙事 + CA/0x/bsc/meme/币安) gives context; untracked authors never count toward a signal.
- BSC CAs (0x...) are parsed, priced on DexScreener/GeckoTerminal, and checked with GoPlus.
- Copy-paste campaigns (>=3 accounts with near-identical text, or 2 exact copies) mark their CAs/$tickers as shilled, which blocks a BUY for 48h.

## Dashboard Page refresh (optional last step of each run)
Page: "Memecoin Narrative Tracker", canvas_id `610c706b-79d2-4857-9fe8-d9ee6693f367`.
```
python3 dashboard_data.py --tsx > runs/RUN/dashboard_block.tsx   # new data block for the latest run
```
Then the agent calls ReadCanvas on that canvas_id, copies the current text from `// DATA:START` through `// DATA:END`,
and calls EditCanvas once: old_string = that block, new_string = the contents of dashboard_block.tsx.
Only the RUN, NARR and COINS constants change. Callers, rules and back-test are static: edit them by hand when callers.json or the back-test changes.
`python3 dashboard_data.py > runs/RUN/dashboard.json` writes the same data as JSON.

## BUY rule (every condition must pass)
1. Confluence (caller-led): at least 2 distinct non-flagged tracked callers posted the CA (or a $ticker resolved to it) on X within 6h, OR 1 tier-A caller plus a strong X spike (at least 15 posts in the last full hour and at least 3x the prior-6h hourly average).
   OR narrative-led: the coin is a top-2 leader of a NEW/RISING/HOT narrative whose X keyword count is spiking, and at least 2 organic (non-paid) feeds list it.
2. Narrative starting: CA mentions in the last full hour are at least 5, at least 2x the prior-6h hourly average, and at least 50% of the 72h peak hour (this filters out coins already fading). For a narrative-led coin, the narrative's X keyword spike stands in.
2b. Not wash-traded (Jupiter organic score is not "low") and not part of a copy-paste shill campaign. These two blockers still override any smart-money or KOL booster.
2c. Boosters / confidence upgrades (optional; never a BUY on their own): **smart-money confirmed** if at least 2 tracked wallets in `smart_wallets.json` bought the coin in the last ~1h (Helius stream or poll), or GMGN shows a smart-money cluster buy in that window (>=2 distinct `track smartmoney` wallets, or market signal type 12). **KOL buy** if a tracked wallet tagged `kol` bought in the last ~1h, or (when a key is present) GMGN `track kol` / market signal type 20. Confidence is labeled `standard`, `narrative (lower)`, `KOL buy`, `smart-money confirmed`, or `smart-money confirmed + KOL buy`.
3. Liquidity of at least $10K; market cap between $20K and $25M.
4. Not late: less than 10x since the first tracked call, and the 1h price change is no more than +300%.
5. Pair age between 15 min and 7 days.
6. In the last hour, buys are at least equal to sells.
7. Solana - RugCheck: mint authority none, freeze authority none, not rugged, no "danger" risks, top-10 non-pool holders at most 30%, creator wallet at most 5%. BSC - GoPlus: not a honeypot, buy/sell tax <=10%, not mintable by a live owner, no hidden owner / take-back ownership / cannot-sell-all, top-10 non-contract holders at most 30%, creator at most 5%.
Notes are attached when a coin is still on the bonding curve or when flagged accounts are also pushing it.
WATCH means a tracked caller is in but at most 2 conditions are missing, or there are no callers and only 1 condition is missing.

## SELL rule (for coins that got a BUY)
Hard exits (any one triggers a SELL): price down 35% from the signal (stop-loss); trailing stop at -30% from the post-signal peak once the coin has been up 30% or more; liquidity down 30% or more since the signal; creator wallet sold 50% or more since the signal; RugCheck marks the token rugged.
Soft exits (2 or more trigger a SELL): the coin's narrative is FADING; last-3h mentions down 60% or more from the peak hour; no tracked-caller post in 12h; negative caller words (rug, dump, sold, jeet, dead, ...); 1h volume below 30% of the 6h hourly average; 1h buys/sells below 0.8; take-profit zone reached (2x, sell at least half); a tracked smart-money or KOL wallet (or GMGN, if keyed) sold a previously signaled coin in the last ~1h.

## Pump.fun Callout Rewards leaderboard (boost only)

`pumpfun_callouts.py` loads `data/pumpfun_callout_leaderboard.json`, a dated snapshot of the public Callout Rewards board (daily / weekly / monthly / all-time). Ranks and rewards from after the 10 Oct 2026 follower-profit change are weighted more than all-time; a high call-frequency penalty applies only when a source published a call count; caller wallets flagged as bot-like, wash-like, sybil, or bundled get no boost.

This is an extra input next to the existing 24h-2x caller hit rate. **A callout or a leaderboard rank alone never creates a BUY** — it only adds a plain-English boost note when a coin already has an independent signal.

