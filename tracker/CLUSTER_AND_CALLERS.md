# Free GMGN cluster replacement + caller-chatter wiring

Researched 9 Nov 2026, America/Chicago. Research only; no code was changed, no credentials used, no paid accounts, no trades.

Goal: replace GMGN's "2+ smart wallets / KOLs bought the same mint in a short window" signal. GMGN's Agent API is out because the free key needs a $100 account balance.

## Recommendation

**Best free replacement: do the clustering yourself on the Helius free plan Anish already has, plus a public KOL/smart-wallet list.**

This is already how `smartmoney.py` confirms a cluster when GMGN is missing: `smart-money confirmed` if **2 or more tracked wallets buy the same mint within about 1 hour** (`WINDOW_S = 3600`, `cluster_by_mint` / `summarize`). What GMGN added was a *much larger labeled universe*. The free way to get that universe back is not another paid "smart money API" — it is to watch a longer public wallet list in real time, then keep the same 2-in-1h rule.

### Why Helius, specifically

Helius Free is $0, **no card required**, 1M credits/month. The existing key is enough.

| Path | Free-plan facts | Fit |
| --- | --- | --- |
| **Enhanced webhooks** (recommended for a public HTTPS receiver) | 5 webhooks, **100,000 addresses each**, filter `transactionTypes: ["SWAP"]`, **1 credit per delivered event**, 100 credits to create/edit/delete. Free webhooks are auto-disabled if delivery fails ≥95% over 24h. | Best for a long-lived alert service (`smart-money-alerts`) with a public URL. Watching 50–500 KOL wallets of SWAP events is cheap vs polling. |
| **Parsed Streams** (`parsedTransactionSubscribe`) | Documented as **available on all plans, including Free**. 1 credit per event (same as webhooks). Connect `wss://beta.helius-rpc.com/?api-key=...`. Filter by `accounts.include` (the wallet list). Search-indexed docs also mention 5 concurrent WS connections and 25 subscriptions per connection on Free; confirm in the dashboard before relying on those caps. Distinct from "Enhanced WebSockets", which are **not** on Free, and from LaserStream gRPC, also not on Free. | Best if a process can stay connected (no public URL needed). |
| **Current polling** (`GET /v0/addresses/{address}/transactions`, type=SWAP) | Already wired. Enhanced parsed history costs **100 credits/request**, 2 req/s, and the code caps at **12 wallets / 20 calls per run**. 20 calls × 100 credits = 2,000 credits/run, so a tight cron (e.g. every 5–15 min) can burn the 1M monthly credits. | Works today for the 10 wallets in `smart_wallets.json`. Do not scale the list on this path. |
| Cheaper future poll (not wired) | `getTransactionsForAddress` is 10 credits per 100 full txs (signatures-only is 10 flat). **Parsed Events** are 10 credits/request on all plans. `getTransfersByAddress` is **Developer+ only** — do not use it on Free. | If you stay on cron, switch off the 100-credit Enhanced history endpoint. |

Webhooks and Parsed Streams are the actual GMGN replacement: same 2+ makers / 1h rule, but the watch list can grow far past 12. Polling 12 wallets remains a fallback when no receiver or long-lived socket exists.

### Wallet list (the other half of the replacement)

GMGN's value was the labeled set, not the clustering math. Free sources of full addresses:

- Existing `smart_wallets.json`: 10 public Solana wallets from [Solana Trading's 2 Nov 2026 recap](https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-october-2026) of KOL Explorer's 1 Nov 2026 30-day realized-PnL board.
- [kolscan.io](https://kolscan.io) account pages exist (`/account/<address>`), but the public leaderboard HTML **truncates** addresses, so it is a poor scrape target. Prefer write-ups or account URLs that already publish the full string.
- Keep adding manually reviewed public leaderboards. Do not sign into Cielo/Kolscan/Nansen to unlock hidden lists.

### How this plugs into the two codebases (when Anish asks to build)

**`tracker/smartmoney.py`**

- Keep `cluster_by_mint`, `summarize`, and the rule "2+ tracked wallets in ~1h". Without GMGN, `sm_confirmed` still fires from `helius_buyers`.
- Leave `HELIUS_MAX_WALLETS = 12` and `HELIUS_MAX_CALLS = 20` on the polling path.
- New optional collector: webhook or Parsed Streams events → same `{mint, maker, side, timestamp}` shape → feed `cluster_by_mint`. That path can drop the 12-wallet cap.
- GMGN blocks (`gmgn_sm`, type-12 / type-20 signals, KOL buy/sell) stay optional and dark until a key exists without a $100 balance.

**`src/sma/sources/`**

- `solana.py` already polls Helius Enhanced history when `HELIUS_API_KEY` is set. `pipeline.py` already treats other graded wallets buying the same token as `cobuyers`.
- Add a webhook/stream source next to `solana.py` / `gmgn.py`. Parse SWAP/buy events, store them, and let the existing cobuyer + wallet-grade path do the "cluster in one message" work.
- `gmgn.py` stays a read-only optional source.

A public HTTPS endpoint is the main operational gap for webhooks (the current tracker is a polling routine). Parsed Streams avoids that if a worker can stay online. Either way, do not place trades.

## Runner-ups

### 1. Cielo free web/Telegram, plus a thin free `/feed` API

- **Web/Telegram (no paid plan):** track **50 Solana** wallets and 250 EVM wallets, 5 tokens, 5 lists, **1 Telegram bot**, 120 alerts/hour. Good as a personal side-channel, not as a programmable cluster.
- **Free developer API:** 5,000 credits; **only** `GET /api/v1/feed` (3–5 credits; 3 for a narrow `wallet` / `chains=solana` / `txTypes=swap` query) and `GET /api/v1/chains` (0 credits). **No WebSocket** on Free. Wallet-tracking CRUD, tags, PnL, and Telegram-bot listing are **Builder $89/mo / Architect $188/mo**.
- You can poll `/feed` for wallets you already know and still run `cluster_by_mint` yourself. 5,000 credits is roughly 1,000–1,600 feed calls per cycle (reset not independently re-verified here). It needs a Cielo API key (signup), but **no $100 balance**.
- Pro web tracking is $59/mo ($49 annual) and is not required, and should not be used without a yes.

### 2. Birdeye Data Services Standard (free, no card)

- **30,000 compute units/month, 1 RPS, REST only. No WebSocket on Standard.** Account signup, **no credit card**.
- **On Standard (useful):** `GET /defi/v2/tokens/top_traders` (can filter Solana tags including `smart_trader`; 30 CU), `GET /trader/gainers-losers`, `GET /trader/txs/seek_by_time` (12 CU), token/pair trades, some wallet v2 net-worth / PnL summary / leaderboard endpoints.
- **Not on Standard:** `GET /v1/wallet/tx_list` and wallet portfolio (Lite+), `GET /smart-money/v1/token/list` (**Starter+**, paid).
- 30k CU cannot poll a 12–50 wallet list on a tight cron (`12 CU × 12 wallets × 96 polls/day` blows the month in about two days). Use it as a **supplement**: when the tracker already has a candidate mint, ask top-traders / `smart_trader` tags, or sparsely pull `trader/txs/seek_by_time`.

## Other vendors (not a replacement)

| Source | Free reality | Verdict |
| --- | --- | --- |
| **Nansen API** | Free: 100 trial credits, then a daily top-up to **10 credits**. Smart Money endpoints (`/smart-money/netflow`, holdings, dex-trades, etc.) cost **5 credits** each, so about two SM calls/day after the trial. Premium labels cost 50. Pro is paid. | Not usable as a live cluster feed. |
| **Bitquery** | **No permanent free plan.** 7-day trial, 1,000 API points, no card; then Personal from ~$29–49/mo. Solana DEXTrades GraphQL exists but is not free ongoing. | Out. |
| **Dune** | Free is view-only: **no API**, no query execution, no credits. API starts with a trial or Analyst ($75/mo). | Out. |
| **Solscan** | Marketing/docs describe a free Level 1 key with limited core/network endpoints (one secondary source says 10M CU/month). Lite is **$49/mo**, 20M CU, 1,000 req/60s, and account-transaction style Pro endpoints live there. | Not a clean free wallet-history API for clustering. |
| **SolanaFM** | Free: **$0, 10 RPS**, APIs + webhooks, 1 GB bandwidth. `GET /v0/accounts/:hash/transactions` and `/transfers` at 10 RPS. A free key is commonly used to raise limits. | Honest runner-up infrastructure, but Helius is already keyed and parses swaps better. Keep as backup poll/webhook. |
| **Shyft** | Free: 10 RPC req/s, 1 API req/s, unlimited credits on the current RPC pricing page; **no gRPC**. Callback/webhook APIs are **deprecated** in favor of Yellowstone gRPC (paid). | Not a cluster source on Free. |
| **DexScreener / GeckoTerminal public APIs** | Pools, prices, OHLCV, some trades. **No official top-traders or wallet-cluster endpoint.** Third-party "top traders" scrapers are unofficial and should not be used. | Already used for prices/narratives only. |

## Open-source repos (2025–2026 search)

No maintained MIT/Apache library was found that is a drop-in "smart-money cluster detector" (2+ labeled wallets, same mint, short window). Almost everything with "copy trade" in the name is a **trading bot**. Do not clone those for this project.

| Repo | Stars | License | Language | Last push | Notes |
| --- | --- | --- | --- | --- | --- |
| [thelezend/solana-copy-trade-detect](https://github.com/thelezend/solana-copy-trade-detect) | 54 | Apache-2.0 | Rust | 2024-12-15 (**archived**) | CLI to test if *one wallet* is copy-trading others. Not a live cluster alerter. |
| [nirholas/kol-quest](https://github.com/nirholas/kol-quest) | 28 | no SPDX (`NOASSERTION`) | TypeScript | 2026-11-04 | KOL leaderboard; previously noted as scraping GMGN (blocked from this box). |
| [1f1n/Dragon](https://github.com/1f1n/Dragon) | 183 | none stated | Python | 2025-11-21 | Wallet-finding toolkit, not a cluster API. |
| [AtlasOnchain/Atlas](https://github.com/AtlasOnchain/Atlas) | 35 | none stated | TypeScript | 2026-06-22 | "Smart money tracker" / whale alerts; review license before any use. |
| [AccursedGalaxy/Insider-Monitor](https://github.com/AccursedGalaxy/Insider-Monitor) | 41 | none stated | Go | 2026-10-21 | Wallet activity monitor. |
| [DracoR22/handi-cat_wallet-tracker](https://github.com/DracoR22/handi-cat_wallet-tracker) | 209 | none stated | TypeScript | 2026-02-17 | Telegram wallet tracker, not a cluster lib. |
| Many "solana-copy-trading-bot" repos (400–4,500 stars) | — | mixed / often none | Rust/TS | 2025–2026 | **Trade-execution bots. Out of scope.** |

DIY on Helius plus `cluster_by_mint` is cleaner than adopting any of the above.

---

## Goal 2: opentwitter-mcp and caller grades

### Repo facts (GitHub, 9 Nov 2026)

- URL: https://github.com/6551Team/opentwitter-mcp
- Homepage: https://6551.io/mcp
- **1,439 stars**, 102 forks, **MIT**, **Python**
- Created 26 Feb 2026; last push **22 Sep 2026**; repo metadata updated 6 Nov 2026
- Install/docs also at [NewsLiquid Skills](https://docs.newsliquid.com/en/mcp-services) and [Membership and PTS](https://docs.newsliquid.com/en/plans-and-points)

### Auth — not an X cookie, not the official X API

The server is a thin MCP client. It talks only to **6551's hosted API** (`https://ai.6551.io`, optional `TWITTER_API_BASE`). Required env: **`OPENNEWS_TOKEN`**, a Bearer token created at [app.newsliquid.com/mcp](http://app.newsliquid.com/mcp) after **signing in and passing human verification**. Token can also live in a local `config.json`.

It does **not** use an X username/password, cookie, or official X developer token. Do not use Anish's X login or any saved password.

**Cost:** the *repo* is free MIT software. The *data* is metered NewsLiquid **PTS**.

- Docs describe **free daily PTS** that reset each day, but **do not publish the daily amount**.
- On every membership level (including free), basic tools are billed, e.g. search tweets / get user tweets = **1 PTS per 20 results** (a short page still costs 1 PTS); get user = 1 PTS; follower/deleted/KOL-follower/quote lookups = 1 PTS (quotes 1 PTS per 20).
- **`add_twitter_watch`, monitor list, and Twitter live WSS are Max-plan only.** WSS is `wss://ai.6551.io/open/twitter_wss?token=...` at 1 PTS per 5 unique messages. Do not buy Max or PTS without Anish's yes.
- Token creation is a 6551/NewsLiquid account, not a $100 on-chain balance, but it is still a third-party signup.

### Tools the MCP exposes

`get_twitter_user`, `get_twitter_user_by_id`, `get_twitter_user_tweets`, `search_twitter`, `search_twitter_advanced`, `get_twitter_follower_events`, `get_twitter_deleted_tweets`, `get_twitter_kol_followers`, `get_meme_token_evidence`, `get_meme_activity`, `get_twitter_article_by_id`, `get_twitter_tweet_by_id`, `get_twitter_quote_tweets_by_id`, `get_twitter_retweet_users_by_id`, `get_twitter_watch`, `add_twitter_watch`, `delete_twitter_watch`.

Meme tools return fomo/pump-style thesis/callout evidence and later buy/sell statements — useful for joining a tweet to a mint. Watch/WSS tools should be treated as paid-Max and skipped on free.

### ToS / policy risk

6551 redistributes Twitter/X data through its own API. That is **not** the official X API. X's terms generally restrict unauthorized scraping and resale. Using this in a public, always-on product has **policy risk** (account or key revocation, data gaps). Safer options: Grok Bot's built-in X read tools, or the official X API with a bearer Anish explicitly provides. Never paste the NewsLiquid token into chat, git, or docs.

### Wiring plan (caller grades into the same alerts)

The grading path already exists. Do not reinvent it.

1. **Caller list:** `memecoin-tracker/callers.json` and `smart-money-alerts/data/callers.json` (tier A/B, zh KOLs, flagged, catalysts). Flagged and catalysts must stay out of the hit-rate grade, as today.
2. **Ingest interface:** `sma/sources/xapi.py` already defines `posts_about(symbol, address) -> [{author, text, ts}]`. Add a second adapter with the same shape:
   - **Preferred, no Anish credentials:** Grok Bot `x` namespace — `get_users_by_username` / `get_users_by_usernames`, `get_users_posts`, `search_posts_all` (and related read tools). These are built-in official X reads.
   - **Standalone MIT tool today:** official `X_BEARER_TOKEN` recent search (already wired). Needs Anish's X API bearer; Free/Basic official X search is tight.
   - **Optional later:** OpenTwitter (`search_twitter` / `get_twitter_user_tweets`, plus `get_meme_token_evidence` / `get_meme_activity` to extract a CA/mint). Use only after a NewsLiquid token is created **by Anish**, and stay on free-PTS polling — no Max WSS, no `add_twitter_watch`.
3. **Cadence:** on each `sma run` (and the tracker narrative pass), search recent posts for the token mint and `$symbol` (current `xapi.py` query). Optionally, on a slower timer, poll `get_users_posts` for each tracked handle and extract contract addresses from text/URLs. Stay inside whatever budget the chosen source has (PTS, X API, or bot tool limits). A 5–15 minute poll matches the late-copy window; do not stream unless a paid Max plan is approved.
4. **Join to mint:** regex/base58 CA in the tweet, expanded URLs, and (if OpenTwitter is on) meme-evidence fields. Map `(chain, mint)` onto the alert in `pipeline.py` the same way `hub.x_posts` does now.
5. **Grading (already in `grading/caller.py` + `pipeline.score_ledger`):**
   - Hit rate = share of detected calls whose **24h peak reached 2x** the price at first-call timestamp.
   - Published "NN% of MM" in the note is a weak prior (1/3 weight), shrunk toward a 30% base.
   - Grades A/B/C/D; three independent tracked callers bump B→A or C→B.
   - `story.py` already writes the caller grade into the alert text. `narratives.py` / `grading/narrative.py` stay the story layer.
6. **Comparison — use built-in X reads first.**

| | Grok Bot `x` tools | Official X bearer (`xapi.py`) | opentwitter-mcp |
| --- | --- | --- | --- |
| Anish credentials | None | X API bearer (paid volume likely) | NewsLiquid signup + `OPENNEWS_TOKEN` |
| Cookie / X password | No | No | No |
| Cost | Included with the bot | Official X plan limits | Free daily PTS (amount unpublished) then paid PTS / Max |
| Live watch / WSS | No | No (filtered stream is a separate paid X product) | Max plan only |
| Meme thesis / CA evidence | No special tool (parse text) | Parse text | `get_meme_token_evidence`, `get_meme_activity` |
| ToS | Official X, via the bot | Official X | Third-party redistributor; higher policy risk |
| Best use | Default caller poll for this bot | Standalone tool if Anish gives a bearer | Optional enrichment only, after he creates a token |

Default plan: wire caller polling through the existing `posts_about` slot, backed first by Grok Bot X reads (in this environment) or official bearer (in the MIT repo). Treat OpenTwitter as an optional enrichment for CA/thesis, not the primary feed, and never enable paid watch/WSS without a yes.

---

## Source URLs

- Helius plans / credits / rate limits: https://www.helius.dev/docs/billing/plans · https://www.helius.dev/docs/billing/credits · https://www.helius.dev/docs/billing/rate-limits
- Helius webhooks: https://www.helius.dev/docs/api-reference/webhooks · https://www.helius.dev/docs/faqs/webhooks
- Helius Parsed Streams: https://www.helius.dev/docs/parsed-streams · https://www.helius.dev/docs/parsed-streams/quickstart
- Birdeye accessibility / pricing / FAQs / CU: https://data.birdeye.so/docs/guides/data-accessibility-by-packages · https://data.birdeye.so/docs/guides/payment/pricing · https://data.birdeye.so/docs/resources/faqs · https://data.birdeye.so/docs/guides/what-is-compute-unit-cost · https://birdeye.so/data-api/blog/detail/birdeye-data-services-standard-plan-is-now-7x-bigger
- Cielo plans / API / feed / Telegram: https://docs.cielo.finance/wallet-tracking/subscribe · https://docs.cielo.finance/developer-api/credits-and-plans · https://docs.cielo.finance/api-reference/feed · https://docs.cielo.finance/discord-+-telegram-bots/getting-started
- Nansen: https://docs.nansen.ai/getting-started/credits · https://docs.nansen.ai/api/smart-money · https://nansen.ai/api
- Bitquery: https://bitquery.io/pricing · https://bitquery.io/blog/blockchain-data-api-pricing-free-tiers · https://docs.bitquery.io/docs/blockchain/Solana/solana-dextrades/
- Dune: https://docs.dune.com/api-reference/overview/billing · https://dune.com/pricing
- Solscan: https://solscan.io/apis · https://docs.solscan.io/solscan-api/solscan-api-lite-plan
- SolanaFM: https://docs.solana.fm/reference/rate-limits-1 · https://docs.solana.fm/reference/get_account_transactions
- Shyft: https://shyft.to/solana-rpc-grpc-pricing · https://docs.shyft.to/callbacks/callback-apis-deprecated
- DexScreener / GeckoTerminal: https://docs.dexscreener.com/api/reference · https://api.geckoterminal.com/docs/index.html
- Wallet lists: https://solana-trading.com/blog/top-10-solana-memecoin-trader-wallets-october-2026 · https://kolscan.io
- opentwitter-mcp: https://github.com/6551Team/opentwitter-mcp · https://docs.newsliquid.com/en/plans-and-points · https://docs.newsliquid.com/en/mcp-services · http://app.newsliquid.com/mcp
