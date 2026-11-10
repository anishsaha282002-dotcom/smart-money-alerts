# Trial-readiness plan: from working prototype to a 10–20 trader private trial

Written 10 Nov 2026 for the next build session. Read this whole file before writing code.

**The product rule, which overrides everything below:** the app reports what wallets and callers
*did*, how reliable they have been, and what to watch out for. It never tells anyone to buy or sell,
never says "why to buy", and never claims to be the best caller until its own public record shows it.

---

## 0. Where things stand (checked on the live branch, not from memory)

| Fact | Evidence |
|---|---|
| Default branch is `smart-money-stories`; the port from `main` is merged (PR #1) | `git log origin/smart-money-stories` |
| `scan.yml` **has now run once** (`scan: 2026-11-10T13:43Z`); `record/ledger.jsonl` has 3 `sm_selling` lines | `record/ledger.jsonl` |
| 141 tests pass on this branch | `pytest -q` |
| Tracked wallet list: `data/smart_wallets.json`, about 1,160 entries; 779 come from `nirholas/kol-quest/solwallets.json`, 347 from a kolscan leaderboard copy | `source` field per wallet |
| **`overnight-upgrades` (fe20078) is NOT on GitHub.** It only exists where it was built | `git ls-remote --heads origin` lists `main`, `port-from-main`, `smart-money-stories` only |

**Step 0 for whoever builds next:** push `overnight-upgrades` and open it as a PR into
`smart-money-stories`. Everything below assumes its work (backtest, RugCheck line, reconnect fix,
bot flags, logsSubscribe listener, Telegram reader) is in. Do not rebuild those.

---

## Phase 1 — Correctness first (blocks the trial)

A single wrong contract address in a trader group ends the trial. This phase comes before features.

### 1.1 Fix pair parsing properly (the Dacity / TTWO bug)

**What is wrong today.** `sms/sources/helius_stream.py:151` (`parse_swaps`) walks every
`tokenTransfers` row and records a *buy* for any non-quote mint arriving at a tracked wallet, and a
*sell* for any leaving. `QUOTE_MINTS` (line 37) only knows WSOL, USDC, USDT and USD1. So in a
memecoin↔memecoin swap (Dacity paired with TTWO) **both** mints are recorded, one as a buy and one as
a sell, and either can surface as "the coin".

**Do this instead (net-delta + role resolution):**

1. For each tracked wallet in the transaction, sum the **net change per mint** across all transfers,
   counting native SOL and WSOL as one asset. Intermediate router hops net to zero and disappear.
2. Keep mints with a non-zero net change. Drop known quotes (WSOL, USDC, USDT, USD1, and any mint
   in a small `quote_mints` config list).
3. If exactly one non-quote mint changed: that is the coin. Positive = buy, negative = sell.
4. If two non-quote mints changed in opposite directions (token↔token), decide which one is the
   memecoin, in this order, and **cache the answer** in a `mint_role` table:
   1. **Pump.fun origin (authoritative).** The mint was created by the pump program
      `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` (`create` or `create_v2` instruction), or a
      bonding-curve account exists for it. Confirm the discriminators against the official IDL in
      `pump-fun/pump-public-docs` before relying on them.
   2. **Pool roles.** Ask GeckoTerminal `/networks/solana/tokens/{mint}/pools`. A mint that is the
      *quote* side in most of its pools is a quote. Do not rely on DexScreener's `baseToken` alone; it
      can swap sides on token↔token pools.
   3. **Otherwise: ambiguous. Do not alert.** Store the swap with `role="unclear"` and both mints.
   The `…pump` address suffix is only a weak hint (anyone can grind a vanity address). Never decide on
   it alone.
5. **Corrections never edit the ledger.** For every past alert that used a quote token as the coin,
   append a `type: "correction"` line (`alert_id`, `wrong_mint`, `right_mint`, `reason`). The site
   shows corrected alerts with a visible "corrected" tag. Visible corrections build trust; silent
   edits destroy it and break the hash chain.

**Tests to add (fixtures from real transactions):** Dacity/TTWO; a memecoin bought with USDC; a
pump.fun coin before and after graduation to PumpSwap
(`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`); a two-hop route via an intermediate token; an
ambiguous token↔token pair that must produce no alert.

**Done when:** the Dacity case yields `nxPqZ4F7ux8Vph5NFu25rEP6Kx9Gr1U6Fmj36Rjpump`; the ambiguous
fixture yields no alert; correction lines exist for every affected past alert; tests pass.

### 1.2 Hand-checked accuracy audit

Write `scripts/audit_sample.py`: pick 50 recent alerts at random and print, for each, a Solscan link
for the transaction, the wallet, the mint and the USD amount. A person checks every row on
Solscan and fills in `docs/audit-YYYY-MM-DD.md` with "correct / wrong (why)".

**Done when:** 50 of 50 are correct, or every wrong one has a fix, a test and a correction line.
Repeat the audit once a week during the trial.

### 1.3 Check the wallet list's provenance

About 1,126 of the tracked wallets come from third-party GitHub repositories and a leaderboard
snapshot. Before sharing with a group:

- Check each source repository's license. Unlicensed data may be listed as a *source to look up*,
  but not redistributed in `data/smart_wallets.json`.
- Remove wallets whose only evidence is a blog post.
- Give each wallet a `first_seen` date, so the backtest can avoid picking wallets with hindsight
  (see 3.3).

---

## Phase 2 — Always-on and observable (blocks the trial)

### 2.1 Give the live stream a home that never sleeps

GitHub Actions runs every ~30 minutes and is often late. That is fine for the public record and the
website, but useless for memecoin alerts. The Helius stream worker (`sms/stream_worker.py`) must run
somewhere 24/7.

| Option | Cost | Fit |
|---|---|---|
| **Oracle Cloud Always Free VM** | Free | Best free fit: a real VM that does not sleep. Verify current terms on Oracle's site |
| A spare computer or Raspberry Pi at home | Free | Simple. Stops when the machine sleeps or reboots |
| Render / Koyeb free tiers | Free | **Not suitable:** free services sleep, and the websocket drops |
| Railway | ~$5 credit/month | Works while the credit lasts. Not "free forever" |

Ship a `deploy/` folder with a systemd unit (auto-restart, single-instance lock already exists), a
`.env` template, and a one-page setup guide written for a non-technical owner. The worker writes
alerts to the same ledger and pushes them to Telegram; the GitHub site keeps updating from the
scheduled scan.

### 2.2 Health you can see

Add a small health strip to the site and a `/health` JSON from the worker:

- last event received (time), subscriptions up (e.g. 9/9), reconnects in the last hour
- last scan time, Helius credits used this month vs the 1M free budget
- **alert latency:** chain time of the buy → time the alert was sent, as a median for the last day

The trial group will judge the product on latency first. Show it, don't hide it.

**Done when:** a 24-hour run shows 9/9 subscriptions throughout, median latency is displayed, and
pulling the network cable produces a visible "stale" state and an automatic recovery.

---

## Phase 3 — Trust features (the reasons to pick this over an $849 tool)

Order matters. Build in this order.

### 3.1 Forward record from alert time (most important)

The backtest is useful but it is *in-sample*: it measures wallets that were chosen knowing how they
did. The only number a skeptical trader trusts is a record built **after** the alert was published.

- Every alert stores the **alert-time price** (already the scoring basis) and the **delay** between the
  wallet's buy and the alert.
- The 7-day paper log: a fixed $100 into every alert at the alert-time price, marked at +15m, +1h,
  +4h, +24h, +7d. Misses stay. Fees and slippage are stated as excluded, or modelled as a flat 2% per
  side and labelled.
- The record page shows forward results separately from backtest results, and says which is which.

### 3.2 Copy-lag warning on every alert

"This alert reached you X seconds after the wallet bought. The price has already moved Y% since."
If Y is above a threshold, show **"Late: most of the move may already be gone"**. This is the
honest version of what paid tools sell as speed.

### 3.3 Honest base rates

The overnight backtest numbers need three changes before anyone outside sees them:

1. **Out of sample.** Choose wallets using data up to date D, measure their alerts after D. Report
   both, labelled.
2. **Show n and a range on every percentage.** "Touched 2x: 33–41% (17–25 alerts)" becomes
   "Touched 2x: 37% of 21 alerts, likely range 18–59%". Use a Wilson interval. Hide any rate with
   fewer than 30 alerts behind "not enough data yet".
3. **"Touched 2x" is not "could sell at 2x".** Keep the touch metric, add the close-at-+1h and
   close-at-+24h numbers next to it, and say plainly which is which.

### 3.4 Hold / sell tape for tracked wallets

If the wallet that triggered an alert has since sold some or all of its position, the alert card and
the Telegram message must say so ("Sold 60% 14 minutes after buying"). An alert for a position the
wallet has already left is the most damaging false signal there is.

### 3.5 Call-vs-chain timeline (the differentiator)

For each caller with a known wallet: did that wallet buy before posting, and sell after followers
arrived? Show a simple timeline on the caller's card: *bought → posted → sold*. Rate callers who
routinely sell into their own calls as **"sells into own calls"**. MemeGram does a version of this for
Telegram callers only; nobody combines it with wallet grades.

### 3.6 Linked wallets ("big traders don't use their real wallets")

Funding-source clustering: for each wallet, find who sent its first SOL (one cheap lookup per wallet,
cached forever). Wallets funded from the same source, or from a tracked wallet, are shown as
*"probably linked"*. Exchange hot wallets are excluded (crawl-hive's rule: a funder holding more than
~5,000 SOL is treated as an exchange). Always label it as a probability, never as an identity.

---

## Phase 4 — Trial operations

- **Channel:** a private Telegram channel for alerts plus a separate group for feedback. Invite only.
- **Volume control:** at most N alerts per hour (start with 6), deduplicated per coin, cluster
  alerts merged into one message.
- **Feedback:** two inline buttons per Telegram alert ("useful" / "not useful"), stored with the
  alert id. A three-question form every Friday.
- **Onboarding message** (pinned): what an alert means, what the grades mean, what it is not
  (not advice, not a buy signal), where the public record is, how to report a wrong alert.
- **Kill switch:** one config flag that stops all outgoing alerts while keeping the record running.
- **Terms:** a short "alerts only, not financial advice, no guarantees, you trade at your own risk"
  page linked from every message. Not legal advice; have someone qualified read it before going
  public.

### Trial success criteria (decide before starting)

| Measure | Target after 2 weeks |
|---|---|
| Wrong contract addresses | 0 |
| Weekly audit accuracy | 50/50 |
| Median alert latency | Under 60 s (stream), stated honestly if not |
| Worker uptime | Over 99% |
| "Useful" share of rated alerts | Over 50% |
| Testers still reading in week 2 | At least 10 |

Go public only if all are met.

---

## Phase 5 — After the trial

- **Narrative matching v2.** Free, ToS-safe sources first: Telegram public channels (already built),
  Pump.fun comments, Reddit (official API: free tier is non-commercial and about 100 requests per
  minute; new keys may need manual approval). X stays optional: search needs a paid tier, GMGN
  call-outs are the free substitute. **Skip TikTok, Douyin, Xiaohongshu and Weibo** for now: no
  free API, and scraping breaks their terms.
- PumpSwap swap decoding (beyond what Helius parses), graduation watch.
- Base and BSC back on, once Solana is solid.

---

## Wording rules for every alert, page and Telegram message

| Never write | Write instead |
|---|---|
| "Why to buy" | "Why it's on the radar" |
| "Strong buy", "aping", "send it", "next 100x" | Who bought, how much, their record |
| "Best caller on the planet" | The caller's forward hit rate and sample size |
| A percentage without its sample size | "37% of 21 alerts" |
| Nothing about risk | "What would make this wrong": wallet already sold, insiders hold a lot, narrative fading, late alert |

Every message ends with: "Alerts only, not financial advice. This tool cannot trade."

---

## Out of scope, permanently

Trading, signing, private keys, seed phrases, wallet connections, paid data tiers, API keys in the
repository. `tests/test_no_trading.py` must keep passing.

---

## Sources checked for this plan

- Helius limits (free 1M credits/month; 100k addresses per webhook; webhook events 1 credit each):
  https://docs.helius.xyz/docs/billing/rate-limits.md · https://www.helius.dev/docs/billing/credits
- Pump.fun and PumpSwap program ids, `create` / `create_v2`: https://docs.solanatracker.io/guides/pumpfun-program.md ·
  https://docs.solanatracker.io/guides/pumpfun-amm · https://docs.bitquery.io/docs/examples/Solana/Pump-Fun-API/
- Free always-on hosting: https://livemy.app/blog/free-hosting-that-doesnt-sleep ·
  https://dev.to/snapdeploy/free-backend-hosting-7-platforms-that-wont-kill-your-api-2026-1i1g
- Reddit Data API free tier: https://data365.co/blog/reddit-api-limits ·
  https://apiserpent.com/blog/free-reddit-api
- Competitor matrix: `docs/COMPETITORS.md`

Third-party pages; confirm limits on each provider's own site before depending on them.
