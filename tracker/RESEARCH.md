# Research: existing narrative trackers, MCPs, Chinese platforms (10 Nov 2026)
"Box" = tested with curl from this machine on 9 Nov 2026 (CST).

## Open-source repos
| Repo | What it does | License | Use here? |
|---|---|---|---|
| [co-numina/narra-app](https://github.com/co-numina/narra-app) (NARRA) | Solana narrative clustering: synonym engine + n-grams + emergent word frequency, then momentum scoring | none stated | Design copied (seed map + emergent keywords); code needs Claude + KV keys |
| [h100envy/gem-search](https://github.com/h100envy/gem-search) | pump.fun bundle/linked-wallet X-ray, clean-launch feed, Grok "Narrative Hunter" on X | MIT, 228 stars | Idea source (bundle checks); hosted bot not integrated |
| [overdosesol/Catalyst](https://github.com/overdosesol/Catalyst) | Reddit/Google Trends/X/TikTok trend clustering + LLM virality scoring, Telegram alerts | MIT | Needs its own API keys + LLM; not used |
| [yllvar/pump-meta](https://github.com/yllvar/pump-meta) | NLTK sentiment on pump.fun launches | none, stale (2024) | No (pump.fun API blocked) |
| [GMGNAI/gmgn-skills](https://github.com/GMGNAI/gmgn-skills) | Official GMGN CLI/skills + OpenAPI: `track smartmoney` / `track kol`, `market signal` (type 12 smart-money buy, type 20 KOL buy), trending; SOL/BSC/Base | MIT | Wired in read-only via OpenAPI in `smartmoney.py` (env `GMGN_API_KEY`). Official CLI was **not** installed (it also bundles swap/order/wallet commands). A hard guard refuses those subcommands. |
| [nirholas/kol-quest](https://github.com/nirholas/kol-quest) | KOL leaderboard (Kolscan + GMGN) with an MCP server | no SPDX | Scrapes GMGN; GMGN often blocks scripted clients |
| [four-meme-community/four-meme-ai](https://github.com/four-meme-community/four-meme-ai) | four.meme agent skills; documents keyless `POST /meme-api/v1/public/token/search` | MIT | Endpoint WAF-blocked from box; used GeckoTerminal `four-meme` dex instead |
| [QuantProcessing/binance-square-cli](https://github.com/QuantProcessing/binance-square-cli) | Unofficial Binance Square CLI + MCP via headless-browser header replay | MIT | Not used (fingerprint replay = workaround of Binance's bot protection) |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | RSS for Binance Square users (`/binance/square/user/:u`), Weibo etc. | AGPL-3.0 | Public rsshub.app is Cloudflare-blocked from box; self-hosting possible later |
| [sendaifun/solana-agent-kit](https://github.com/sendaifun/solana-agent-kit) | Solana agent toolkit + MCP | Apache-2.0 | Trading-oriented; not needed |

## MCP servers
| MCP | Free? | Box test |
|---|---|---|
| CoinGecko remote MCP `https://mcp.api.coingecko.com/mcp` ([docs](https://docs.coingecko.com/ai-integration/mcp-server)) | free, keyless | initialize OK |
| DexScreener: [openSVM/dexscreener-mcp-server](https://github.com/openSVM/dexscreener-mcp-server) (Unlicense), [kukapay/dexscreener-trending-mcp](https://github.com/kukapay/dexscreener-trending-mcp) (MIT), Pipeworx remote `https://gateway.pipeworx.io/dexscreener/mcp` | free | Pipeworx initialize OK; tracker calls the DexScreener REST API directly (same data, no extra hop) |
| Birdeye MCP `https://mcp.birdeye.so/mcp` ([docs](https://data.birdeye.so/docs/agents/birdeye-mcp)) | docs say keyless test access | returned 401 Unauthorized from box |
| Helius MCP `npx helius-mcp@latest` ([docs](https://www.helius.dev/docs/agents/mcp)) | needs Helius key (free tier exists) | not installed; tracker calls Helius REST/RPC directly when `HELIUS_API_KEY` is set |
| GMGN MCP/skills ([docs](https://docs.gmgn.ai/index/gmgn-agent-api)) | needs GMGN API key (exist-auth for queries; private key only for swap) | CLI/MCP not installed; OpenAPI read calls are in `smartmoney.py` when `GMGN_API_KEY` is set |
| LunarCrush MCP | paid (see below) | - |

## Free data endpoints used by the tracker
See README "Sources". Working: DexScreener (metas, boosts, profiles, CTOs, tokens, search), GeckoTerminal (trending sol/bsc, new pools, four-meme dex), Jupiter toptrending + organicScore, PumpPortal websocket (newToken + migration; [PumpPortal guide](https://solbundler.app/blog/pump-fun-api)), Binance Alpha token list, CoinGecko trending, RugCheck, GoPlus.
Blocked (403/WAF): pump.fun frontend-api, gmgn.ai, four.meme API, Binance Square, rsshub.app. Key required: SolanaTracker, Birdeye REST.

## Commercial tools (not used; prices from vendor pages / search, 10 Nov 2026)
| Tool | What | Price |
|---|---|---|
| GMGN | Chinese-run terminal; KOL/smart-money/Twitter monitor; Agent API via key | 1% per trade on the terminal. Query API: create a key at [gmgn.ai/ai](https://gmgn.ai/ai) by uploading a local public key. Docs mention a Free leaky bucket of 5/5 (rate/capacity) and paid Plus/Pro buckets; exact long-term free-key terms were not independently verified. IPv4 only. |
| Axiom, Photon, BullX, Padre, Fomo | Solana trading terminals with trackers | ~1% per trade ([comparison](https://jumpbit.io/en/resources/compare/axiom-vs-gmgn)) |
| Kolscan | KOL wallet PnL leaderboard | free web, no documented API |
| Cielo | wallet tracker / alerts | free up to 50 Solana wallets; Pro $59/mo ($49 annual) ([docs](https://docs.cielo.finance/wallet-tracking/subscribe)) |
| Nansen | smart-money labels, narratives | Pro $69/mo monthly, $49/mo annual ([academy](https://academy.nansen.ai/articles/9412804-about-nansen-pro)) |
| LunarCrush | social metrics API + MCP | $1 per 1,000 requests PAYG; $90 / $300 / $900 per month ([pricing](https://lunarcrush.com/pricing)) |
| Kaito | crypto mindshare/narratives | Pro from ~$833/mo billed annually ([pricing](https://pro.kaito.ai/pricing)) |
| Birdeye Data API | prices, trending, holders | $39 / $99 / $199 / $499 per month ([pricing](https://birdeye.so/data-api/pricing)) |
| Helius | Solana RPC/webhooks (wallet tracking). Free: 1M credits/mo, 10 RPC req/s, 2 DAS & Enhanced req/s; Enhanced parsed history costs 100 credits/request ([rate limits](https://www.helius.dev/docs/billing/rate-limits)) | Free $0, Developer $49, Business $499, Professional $999 per month ([plans](https://www.helius.dev/docs/billing/plans)). Tracker uses only the Free plan endpoints when a key is present. |
| Tweet Catcher | paid X monitor recommended in Chinese BSC guides | not checked |

## Chinese platforms: how memes spread
- BNB Chain is the Chinese meme venue: four.meme (pump.fun clone, BNB-paired, graduates at 18 BNB to PancakeSwap; [MemeFees review](https://memefees.com/reviews/four-meme)), Flap and other launchpads (vanity CA suffixes such as ...4444, ...7777).
- Binance is the catalyst: CZ (@cz_binance) and He Yi (@heyibinance) posts/replies get turned into tokens within minutes; Binance Alpha listing, then spot listing, is the "graduation" path (e.g. 币安人生 moved Alpha -> spot on 7 Jan 2026; [Binance Square](https://www.binance.com/en/square/post/34913577563306)). The BNB Chain foundation has bought Chinese memes (币安人生, 哈基米) ([Binance Square](https://www.binance.com/en/square/post/35059196697201)).
- A Chinese BSC guide ([@xixikawaii, Jan 2026](https://zamantika.com/xixikawaii/status/2013522582885278160)) says: for big narratives follow CZ and He Yi; for second legs add Four/Binance accounts; for filtering follow the Chinese builder group; for scanning watch top wallets. Tools: GMGN web/TG bot, Uxento (free X monitor), Tweet Catcher (paid).
- Distribution: X (Chinese CT) is primary and machine-readable through the X MCP; Telegram/WeChat groups (closed); Binance Square (no public API; blocked); Weibo/Douyin/Xiaohongshu (crypto content restricted in China; no free API from box). Chinese meme creators use offshore launchpads + VPN + P2P USDT ([Bifu](https://www.bifu.co/blog/chinese-meme-coin-launch-activity-global-launchpads-2026)).
- Machine-readable from box: X (MCP), DexScreener `chinese` meta, GeckoTerminal four-meme pools, Binance Alpha list (14 Chinese-named BSC tokens listed), GoPlus.
- Copy-paste shill campaigns are common in Chinese meme search results (seen live: >=4 accounts posting the same BABYDOGE "大v带队" mint ad; 2 accounts posting identical $SI CA text). The tracker now detects and blocks these.

## Chinese KOL handles verified on X (get_users_by_usernames, 10 Nov 2026)
Sources: [Foresight News Chinese Web3 top-200](https://foresightnews.pro/article/detail/84780), the @xixikawaii guide, [r/CryptoTrenching list](https://www.reddit.com/r/CryptoTrenching/comments/1oe4vso/top_10_chinese_kol_bnb_wallets_you_should_track/).
Exist (followers): cz_binance 13.0M, heyibinance 679K, huahuayjy 308K, 0xcryptowizard 230K, 0xSunNFT 212K, BitCloutCat 153K, haze0x 141K, lijiuer1 123K, lanyihou 107K, hexiecs 98K, brc20niubi 94K, CryptoDevinL 90K, realChainDoctor 86K, xixikawaii 72K, 0xmagnolia 66K, Tintinx2021 58K, xingpt 58K, 0xKirara 53K, Unipioneer 53K, liping007 52K, feibo03 43K, yingbinance 39K, corleonefnf 38K, 0xmasiwei 34K, Btc_Dou 22K, hotsaucehong 0.75K.
Not found / unavailable: 0x0xFeng (forbidden), porounclemao, zlexdl, Loki_Zeng, 0xFelixHK.

## Helius + GMGN integration (wired 9–10 Nov 2026 CST)
- Code: `smartmoney.py` (read-only). Keys: env `HELIUS_API_KEY`, `GMGN_API_KEY`. Missing key or failed call → skip that source; report logs `helius: no key` / `gmgn: no key`.
- Helius used for recency: `GET https://mainnet.helius-rpc.com/v0/addresses/{address}/transactions` (Enhanced parsed history, `type=SWAP`, `token-accounts=balanceChanged`, `gte-time`). DAS `getTokenAccounts` / `getAsset` helpers exist but are not required for the 1h buy check. Caps: 12 wallets, 20 Enhanced calls, 0.6s spacing (under the Free 2 req/s DAS/Enhanced limit).
- GMGN used via OpenAPI `https://openapi.gmgn.ai` with exist-auth only (`X-APIKEY` + `timestamp` + `client_id`). Endpoints: `GET /v1/user/smartmoney`, `GET /v1/user/kol`, `POST /v1/market/token_signal`. Chains: sol, bsc, base. Caps: 12 calls, 1.2s spacing (under the documented Free 5/5 bucket, weight 1).
- `smart_wallets.json`: 10 Solana wallets from the public 2 Nov 2026 Solana Trading recap of KOL Explorer's 1 Nov 2026 30-day board, with source URLs. Kolscan HTML truncates addresses; Cielo public lists did not expose full addresses to WebFetch.
- Not verified: whether a newly created GMGN Agent API key stays on the Free 5/5 bucket indefinitely, or if a trial/paid upgrade is later required. Paid Helius tiers were not used.

