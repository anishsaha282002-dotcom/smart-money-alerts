# Competitor scan: "explained smart-money alerts" (10 Nov 2026, CST)

Question: does anything (paid or free) already do all five of these together?

1. **C1 Story alerts**: live, pushed alerts on smart-money wallet buys, written as short plain-English stories that give the wallet's track record, its sample size, and why this buy is interesting.
2. **C2 One-message fusion**: wallet grade, X/Twitter caller chatter and narrative momentum in a single message.
3. **C3 Late-entry check**: an honest "can you still copy it" check that measures how much gain is left if you buy 5 or 30 minutes late.
4. **C4 Chinese BSC + Solana**: four.meme/Binance BSC coverage alongside Solana.
5. **C5 Public record**: a public, checkable track record of the alerts' own performance.

Scores: **Y** = does it as defined; **P** = partial (an element is present but it's on-demand, raw, aggregate-only, or covers one chain or one source); **N** = no or not found; **?** = could not verify.
How I checked: I did not sign up, sign in or contact anyone. Every evidence URL below returned HTTP 200 on 10 Nov 2026 unless noted (403 = the site blocks bots; the page exists).

## Verdict
**Nobody does all five.** No candidate scores Y on C1, C2 or C3 as defined. The best totals are 4 of 5 at partial-or-better:
- **Tachyo** (paid, $849 per 90 days): C1 P, C3 P, C4 P, C5 Y
- **Blackroom Alpha** (paid, $120/mo): C1 P, C2 P, C4 P, C5 Y
- **Binance Wallet Signals** (free with Binance Wallet): C1 P, C3 P, C4 Y, C5 P
- **DeBot** (free, takes trade fees): C1 P, C2 P, C4 Y, C5 P
- **Ave.ai** (free, takes trade fees): C1 P, C2 P, C4 Y, C5 P
- **Quorum** (source visible, but no license): C1 P, C2 P, C3 P, C5 Y. It is Solana only.

## Matrix
| # | Product | Platform | C1 Story alerts | C2 One-msg fusion | C3 Late check | C4 BSC+SOL | C5 Public record | Cost / license | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Tachyo | Web | P: live feed of S/A-tier buys; "Analyst" explains wallets in plain language, but only on request | N | P: "Am I too late?" (median 0.7 h from first S/A buy to verdict); OVERHEATED verdict; smart money vs exit liquidity. No 5/30-min gain figure | P: scores BNB, SOL, Base, ETH, Robinhood; nothing four.meme-specific | Y: every first flag older than 30 days, misses included | $849 per 90 days, closed | https://tachyo.ai/ |
| 2 | Sanji | Web/TG terminal | P: plain-English AI verdict on any wallet (30-day PnL, win rate, style, "would copy?"), on request | N | N | N (Solana) | N | Freemium terminal, closed | https://sanji.app/ai-analysis |
| 3 | Cielo Research Agents | TG/Discord | P: pushed KOL-cluster and fresh-wallet buys, filterable by win rate and PnL; raw data, no explanation | N | N | P (multi-chain; no four.meme focus) | N | Free (50 wallets) / $59 Pro | https://docs.cielo.finance/wallet-tracking/research-agents |
| 4 | Thrive | Web | N: leaderboards, not memecoin push stories | N | P: wallet score rewards wallets still profitable after a simulated 30-minute execution delay (per wallet, not per alert) | P (ETH/SOL/BSC labels) | N | Pro+ paid, closed | https://thrive.fi/docs/smart-money |
| 5 | Alokumi | Web | P: one-line "edge" and "risk" per wallet. It covers Meteora DLMM liquidity providers, not meme buys | N | P: copyability factor; excludes wallets holding under 30 min | N | N | Free leaderboard | https://docs.alokumi.io/smart-money/ |
| 6 | Stable Boy | GitHub/Web | N: 0–100 wallet stability score, on request | N | N | N | N | Free, **MIT** | https://github.com/OpenComDev/stable-boy |
| 7 | MemeGram | Web | N: grades Telegram callers, not wallets | N | P: median follower result at 15 min, 1 h and 6 h after each call, plus a "bought before the post" percentage (callers only) | N | Y: method public; every call counted | Free | https://memegram.space/ |
| 8 | MadeOnSol (API + MCP) | Web/API/MCP | P: each KOL trade arrives with the trader's win rate, percentile and strategy; coordination webhooks. JSON, not prose | P: KOL X profile plus a coordination score; no narrative | N | N (Solana + Robinhood) | ? (has a "Signal Scorecard" page I didn't audit) | Free key (5-min delay) / Pro paid | https://madeonsol.com/solutions/smart-money |
| 9 | Athena Alpha | Web/TG/Discord | P: pushed AI-scored signals from smart-money and KOL wallets; a score embed, not a wallet-record story | P: one AI score built from smart money, KOL exposure, narrative sentiment, X posts and TG/Discord channels. Opaque, not itemised | N | N (Solana) | P: live 24h 2x-hit-rate panel plus a screenshot "wins" page | $100/mo, closed | https://athenaalpha.xyz/ |
| 10 | Blackroom Alpha | Discord | P: elite-buy and wallet-cluster channels; human operators "explain the reasoning" | P: separate channels for elite buys, clusters and caller calls; "narrative alerts" only on the lifetime tier | N | P (lists BNB, SOL, Base, ETH, Robinhood) | Y: Radar grades every call at +1h and +24h and keeps the misses | $120/mo or $950 lifetime | https://www.blackroomalpha.com/ |
| 11 | GMGN | Web/TG/iOS/Android | P: Smart Money and KOL FOMO alerts on Telegram; AI Narration; wallet win rate on its page | P: smart money, KOL, X Tracker and AI narrative all exist on the platform, not in one graded message | N | **Y** (SOL + BSC, four.meme filter) | N | Free; 1% trade fee | https://docs.gmgn.ai/index/gmgn-tg-alert-channel-bot |
| 12 | DeBot | Web/App/TG | P: buy/sell signal cards when several smart or "conspiracy" wallets trade; an AI summary of the token's Twitter within ~10 s | P: smart-wallet cluster plus AI Twitter-narrative summary plus credibility score on one card; no caller grades | N (shows max gain since first alert) | **Y** (SOL + BSC, four.meme filter) | P: gold/silver/bronze 24h heatmap measured from alert price; no overall win rate | Free; trade fees | https://docs.debot.ai/en/basic-features/ai-signal-tutorial |
| 13 | Ave.ai Signal Square (信号广场) | Web/App/TG | P: pushed smart-money cluster-buy signals; buyer wallets' history one click away | P: inputs include narrative heat and KOL Twitter/TG activity; output is a signal card | N | **Y** (BSC-first + SOL) | P: max gain since first push, per signal | Free; trade fees | https://doc.ave.ai/cn/ave.ai-jiao-cheng/pc-duan-shi-yong-jiao-cheng/ave-ai-xin-hao-guang-chang |
| 14 | Binance Wallet Signals (+ open agent skill) | App / agent skill | P: smart-money buy/sell events (real-time push via `baw tracker ws`); an agent writes prose | N (a KOL-holdings indicator, no X chatter) | P: "can I still buy $X?" token status, maxGain, time-to-peak | **Y** (BSC + Solana; Meme Rush) | P: strategy backtests (win rate, gold-dog rate), not a public ledger | Free; skill repo has no license | https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-trading-signal/SKILL.md |
| 15 | OKX Wallet Signal | Web/App | P: "3 KOLs bought / 5 smart money bought" cards with auto-alerts | N | P: shows how much of their position the signalling wallets have already sold | P (SOL shown; multi-chain wallet) | N | Free; trade fees | https://web3.okx.com/signal |
| 16 | chain.fm | Web | P: live channels of curated smart-money/KOL wallets (incl. "BSC 精选聪明钱") | N | N | **Y** (BSC/SOL/Base) | N | Free | https://chain.fm/channel/1342119459246051334 |
| 17 | 985monitor 聪明钱捕手 | Web | N: dashboard, not push | P: top-3 smart wallets per token plus DeepSeek narrative classification | N | **Y** (four.meme + pump.fun) | N | Free | https://985monitor.xyz/smartmoney/ |
| 18 | MemeTracker (memetracker.uk) | TG/Web | N: token calls, not wallet stories | P: leads collected from GMGN, X and TG; AI score 0–100 | P: free feed is released only after the VIP call has run 2–5x (shows the cost of being late; not a calculation) | **Y** (SOL/BSC/Base/ETH/Robinhood) | Y: public API; every push counted in the denominator (peak multiples) | VIP paid | https://memetracker.uk/performance |
| 19 | 4Bit | TG | P: four.meme top-15 wallets with win rate, profit factor and strategy; buy alerts (premium) | N | N | P (four.meme only) | N | Premium, closed | https://4bit.tech/ |
| 20 | Quorum | GitHub + TG + web | P: TG alerts when 3+ A/B-tier wallets buy within 30 min; `/wallet` shows tier and metrics; structured, not prose | P: cluster plus a "non-dumping KOL" upgrade; no X chatter or narrative | P: every signal measured at 15m/1h/4h/24h from the signal time (not "if 5/30 min late") | N (Solana) | **Y**: public dashboard signal log with outcomes (15-min delay). smrtquorum.top returned 502; the Vercel mirror is 200 | Free; source visible, **no license** | https://github.com/d1sease66/quorum |
| 21 | GROUPCHAT | TG | P: FOMO trader buys with the trader's written thesis (their own "why") plus a 0–100 trader score | P: FOMO theses plus pump.fun callouts; no narrative momentum | P: scores replay each call as if bought **~1 min** after the alert, after fees | P (FOMO chains incl. BNB) | P: last 12 calls per trader shown | Trial, then paid; docs only (NOASSERTION) | https://github.com/jfferreira97/groupchat-alerts |
| 22 | Heimi | Web | P: "whale convergence" alerts when 3+ of 55 KOL wallets buy; per-token Claude analysis | P: KOL wallets, CT/X callouts and narrative score feed one analysis; wallets are not graded | N | N (pump.fun) | P: paper-trading balance chart | Closed; token "TBA" | https://heimi.tech/ |
| 23 | Jarvis (Autonomous AI) | TG | P: whale-buy alerts with "wallet hit-rate"; KOL feed that maps X accounts to wallets | P: X + on-chain KOL confluence; no narrative | N | P ("ETH/BSC/BASE shipping") | N | Free tier | https://autonomousintelligence.io/ecosystem |
| 24 | Rats Killers | Web/email | P: whale accumulation alerts | P: KOL X-mention alerts, sent separately | N | N | N | Free agent listing | https://swarms.world/agent/52ce4e12-ed41-4065-acdf-7b5aa3802719 |
| 25 | Hermemes | GitHub | P: cron alerts when an A-grade KOL buys (confidence, BNB size); 25+ profile metrics; agent can explain | N | P: entry market cap, hours after launch, pre-graduation entry rate (earliness, not gain left) | P (BSC/four.meme only) | N | Free, **MIT** | https://github.com/hermemes/hermes-agent |
| 26 | MemeX Agent | GitHub/Chrome ext | N: on-demand analysis | P: smart money + X narrative + Binance Alpha catalyst in one analysis | N | P (BSC only) | N | Free, **AGPL-3.0** | https://github.com/Edwardchennnn/MemeX-Agent |
| 27 | wallet-cluster-detector | GitHub | **P (closest open source to C1)**: score-weighted cluster detector, then a rule reasoner, then optional **Gemini narration**, then TG/Discord plus paper trade | N | N | N (Solana + Base) | P (paper-trade log) | Free, **MIT** | https://github.com/baronguyen001/wallet-cluster-detector |
| 28 | Smart Bird | GitHub | P: four-layer flagship alert (graduation + smart money + liquidity + "social buzz") | P: buzz comes from DexScreener socials and holders, not X callers | N | N | P: tracks its own accuracy at 1h/6h/24h | No license | https://github.com/Savage27z/smart-bird |
| 29 | kol-quest | GitHub/MCP | N: leaderboard and trade feed | P: KOL wallets (Kolscan + GMGN) joined to X profiles | N | P (GMGN BSC wallets) | N | NOASSERTION | https://github.com/nirholas/kol-quest |
| 30 | solana-alpha-tracker | GitHub/MCP | P: 38 verified KOLs, entry-quality engine, subscriptions | P: `alpha_briefing` narrative tool | N | N | N | Free, **MIT** | https://github.com/duolaAmengweb3/solana-alpha-tracker |
| 31 | CALIBER | Chrome ext | N | P: trust badges for X KOL calls (also 143 TG channels) | P: call outcome checked at 15m/30m/1h/4h/12h/24h; dump rate; deleted calls kept | P (claims SOL/ETH/BNB/Base) | Y: scores written to Solana on-chain | 17 users; price not stated | https://chromewebstore.google.com/detail/caliber/fkelefefncjbipiaoeanffmhjpgdkjdl |
| 32 | Frontrun | Chrome ext | N | P: wallet and KOL labels overlaid on X, GMGN and Axiom | N | ? | N | Freemium; described as open source (repo not checked) | https://madeonsol.com/tools/frontrun |
| 33 | CabalSpy MCP | MCP | P: read-only KOL/smart-money/whale data; the LLM answers in prose | N | N | P (SOL/BNB/Base/ETH) | N | Free key, 10k credits/mo | https://www.cabalspy.xyz/mcp/ |
| 34 | StalkChain MCP | MCP | P: alert streams when several tracked traders enter | P: fomo.family theses (written reasons) plus trader win rates | N | P (SOL + EVM) | N | x402 pay-per-call | https://mcpmarket.com/server/stalkchain-mcp |
| 35 | Sova Intel MCP | MCP | P: wallet behaviour HUD (type, win rate, hold time), asked in plain language | N | N | N | N | API key or x402 | https://docs.sova-intel.com/mcp |
| 36 | @bitecong "AI Signal" posts | X | P: a plain-English story per token, with the account's own record inside the post ("signals from this account doubled within ten minutes 33% of the time"). Based on deployer and buyer lists, not wallet grades | P: narrative read of the name; no caller grades | N | **Y** (BSC Flap/four + SOL) | P: a stat in each post; no ledger found | Free posts | https://x.com/bitecong/status/2099544935200596250 |
| 37 | Smart Money Wallet Signals | Product Hunt | P: "explainable AI conviction scoring, WHY smart money moves matter", but for 130+ *institutional* wallets, not memecoins | N | N | N | ? | ? | https://hunted.space/product/smart-money-signals/launches/smart-money-wallet-signals |
| 38 | trenchscope | Web/TG | P: alert when 3 of 514 curated wallets buy within 10 min | N | N | N | P ("selected observations, not the full track record") | Free tier | https://trenchscope.live/ |
| 39 | Smart Money Tracker (SMT) | Discord/Whop | P | N | N | N | P: live win-rate dashboard for premium calls | Paid | https://whop.com/smart-money-tracker-solana/ |
| 40 | Kolscan / Nansen / Arkham / Axiom / Bitquery | Web/API | Kolscan N (leaderboard, no alerts). Nansen P (Smart Alerts set up by chatting with its AI). Arkham P (entity alerts). Axiom P (wallet and X tracker inside the terminal). Bitquery N (data only) | N | N | Nansen/Arkham P (BSC); Bitquery has four.meme data | N | Nansen $49–69/mo; Bitquery paid (7-day trial) | https://docs.nansen.ai/api/smart-alerts |

### Call-tracking "receipts" services (C5 benchmarks, not wallet alerts)
- **SmugCalls**: 12,051 Solana calls released as **CC0** open data, with SHA-256 hashes anchored in Bitcoin daily through OpenTimestamps and a Zenodo DOI. This is the gold standard for a tamper-evident record. https://smugcalls.com/data.html
- **RebateMax**: independently grades 3,775 calls from 16 TG channels. The median call was worth 0.071x after 24 hours, and calls captured within 60 s scored the same as later captures. https://rebatemax.trading/memecoins/callers
- **Called It**: every call graded from the second it fired; free and premium feeds. https://calledit.meme/performance
- **Kombucho/memecoin-gamble-research**: backtest of 4,293 pump.fun callouts (median −12.6% at 1h). It cites a study where a 30-second delay cut +20% hits from 56.4% to 31.4%, which is direct evidence that C3 matters. https://github.com/Kombucho/memecoin-gamble-research
- **PNL Mama** (CEX signal channels, not memes) https://pnlmama.com/ · **MemeSonar** (source of "2 of 469 smart wallets copyable") https://memesonar.app/best-crypto-tools/wallet-trackers

## Open-source projects covering a subset
| Repo | Covers | License |
|---|---|---|
| [baronguyen001/wallet-cluster-detector](https://github.com/baronguyen001/wallet-cluster-detector) | C1-ish: cluster alerts with rule reasoner and optional Gemini narration; paper trades | MIT |
| [hermemes/hermes-agent](https://github.com/hermemes/hermes-agent) | BSC/four.meme KOL profiling (25+ metrics), A-grade buy alerts | MIT |
| [Edwardchennnn/MemeX-Agent](https://github.com/Edwardchennnn/MemeX-Agent) | BSC smart money + X narrative + Binance Alpha catalyst (on demand) | AGPL-3.0 |
| [d1sease66/quorum](https://github.com/d1sease66/quorum) | Wallet tiers, cluster+KOL alerts, signal outcomes, public dashboard (Solana) | **none** (source visible only) |
| [GMGNAI/gmgn-skills](https://github.com/GMGNAI/gmgn-skills) | Official GMGN smart-money/KOL data for SOL/BSC/Base (needs key; can trade) | MIT |
| [duolaAmengweb3/solana-alpha-tracker](https://github.com/duolaAmengweb3/solana-alpha-tracker) | KOL MCP, entry-quality scoring, narrative briefing | MIT |
| [forgottenpeak/soulwinners](https://github.com/forgottenpeak/soulwinners) | Wallet discovery, archetypes, win-rate-filtered TG alerts | MIT |
| [ujanggantung/whale-trace](https://github.com/ujanggantung/whale-trace) | Keyless wallet 0–100 score + watch alerts | MIT |
| [OpenComDev/stable-boy](https://github.com/OpenComDev/stable-boy) | Transparent wallet stability score | MIT |
| [EvoXBT/pumpfun-callouts-bot](https://github.com/EvoXBT/pumpfun-callouts-bot) | Callout alerts with outcome tracking shown in the alert | MIT |
| [LeoFaveroOnSol/xscan-app](https://github.com/LeoFaveroOnSol/xscan-app) | X KOL call win rates | MIT |
| [automatizing/narrative-tracker](https://github.com/automatizing/narrative-tracker) | X trend clustering + LLM briefing | MIT |
| [cudam321/signal-backtest-harness](https://github.com/cudam321/signal-backtest-harness) | Measurement-first backtest of TG signal channels | MIT |
| [alsk1992/smartsniffer](https://github.com/alsk1992/smartsniffer) | GMGN cluster detection + backtester (copy-trader) | MIT |
| [nirholas/intel-mcp](https://github.com/nirholas/intel-mcp), [kol-mcp](https://github.com/nirholas/kol-mcp) | MCP clients for the three.ws smart-money/KOL API | Apache-2.0 |
| [nirholas/kol-quest](https://github.com/nirholas/kol-quest) | KOL leaderboard SOL+BSC + X profiles + MCP | NOASSERTION |
| [co-numina/narra-app](https://github.com/co-numina/narra-app) | Solana narrative clustering | none |
| [Savage27z/smart-bird](https://github.com/Savage27z/smart-bird) | Fused alert + self accuracy tracking | none |
| [garrett0524/cluster-tracker](https://github.com/garrett0524/cluster-tracker), [timitex59/smart-money-solana](https://github.com/timitex59/smart-money-solana), [AtlasOnchain/Atlas](https://github.com/AtlasOnchain/Atlas), [UselessParadox/meme-coins-analyzer](https://github.com/UselessParadox/meme-coins-analyzer) | Basic smart-money alerts (meme-coins-analyzer plans BSC/four.meme + influencer alerts) | none |
| [buddies2705/awesome-memecoin-trading](https://github.com/buddies2705/awesome-memecoin-trading) | Curated list (295+ tools) | MIT |

## What is definitively missing (the gap)
1. **Wallet-record stories, pushed live.** I found no alert that says, in prose, "wallet X: 8 of its last 10 closed trades won (n=10, 60-day window); it buys early and holds about 40 min; here's why this buy matters." The near misses each have one piece:
   - Tachyo and Sanji explain wallets in prose, but only when you ask.
   - DeBot writes prose about the *token's Twitter*, not the wallet's record.
   - wallet-cluster-detector has optional LLM narration but no record or sample-size framing.
2. **Wallet grades, X-caller grades and narrative momentum, itemised in one message.**
   - Athena, Heimi and DeBot blend these into one opaque score or card.
   - Blackroom splits them across separate channels.
   - Nobody grades X callers (CALIBER/MemeGram-style) *and* wallets in the same alert.
3. **A per-alert "gain left if you're 5 or 30 min late" figure.** It exists only as aggregates:
   - Thrive: a 30-min simulated delay, per wallet, paid.
   - GROUPCHAT: a 1-min replay, per trader.
   - MemeGram and CALIBER: follower outcomes at 15/30 min, per caller.
   - Quorum: outcomes at 15m/1h measured from the signal.
   - Binance: "can I still buy".
   - Nobody stamps a 5m/30m late-entry estimate on each alert from that wallet's history.
4. **four.meme BSC and Solana under one English, explanation-first, wallet-graded alert.**
   - The Chinese tools (GMGN, DeBot, Ave, Binance Wallet, chain.fm) cover both chains but are cards and terminals with trade fees.
   - The English story-style tools are Solana-first.
5. **A tamper-evident public ledger for wallet-alerts.**
   - Tachyo, Quorum and Blackroom publish logs.
   - SmugCalls's CC0 data plus Bitcoin timestamps is the standard to copy, but it covers call channels, not wallet alerts.
   - No free open-source project combines a public ledger with C1–C4.

## Caveats
- **Behind sign-in or paywall, not checked:** the alert formats of paid and closed tools (Tachyo, Athena, Blackroom, 4Bit, GROUPCHAT, MemeTracker VIP, Thrive Pro+, Nansen) come from their own public pages and docs; I didn't see live alerts. Telegram bots and Discord servers were not joined (no sign-in or contact), so the content of their actual messages is unverified.
- **Unreachable sites:**
  - shoalbot.com timed out (TLS error 35). A search snippet says it gives "scored signals with wallet history and red-flag reasons" on SOL/BNB/Robinhood, unverified.
  - Product Hunt pages, axiom.trade and intel.arkm.com returned 403 to curl.
  - Reddit: r/SolanaMemeCoins is banned and unreadable, and Reddit threads were mostly not fetchable.
- **X:** 7 public `search_posts_all` reads only. The GitHub search API was used without auth (top ~12 per query, sorted by stars), so obscure repos may be missed.
- **No app-store review:** the iOS/Android checks were limited to listings found in search: GMGN iOS app, Moby, FOMO and LFG Alarm, all alert/trade apps with no C2/C3/C5.
- **Shill noise:** Chinese "DeBot AI 选币" posts on X are a copy-paste shill campaign, so I treated them as noise.
- **Licenses:** many repos have no license, which means "source visible", not open source.
