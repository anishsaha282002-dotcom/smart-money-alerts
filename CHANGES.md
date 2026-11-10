# overnight-upgrades — changes (not pushed, not merged)

Base: `smart-money-stories` @ a2bee0b. Product boundary kept everywhere: alerts only, never a buy or
sell recommendation; trade decisions stay with the user. No keys, no secrets, nothing paid.

## New
- `sms/backtest.py` — pure functions to measure forward returns after a signal (1h / 6h / 24h from
  the alert-time candle close), % that touched 2x, % that fell 50%, max drawdown, "2x before -50%",
  Wilson 95% intervals. Young signals are not scored; unpriced signals are counted, not dropped.
- `scripts/backtest_signals.py` — replays every signal type (N-wallet cluster within 30m/1h/6h,
  KOL wallet bought, Pump.fun Callout Rewards leader's wallet bought, any tracked buy, clusters that
  include a callout leader) on tracked-wallet history + free GeckoTerminal candles and writes
  `data/baserates.json`. Bot-like wallets excluded; same-second / same-tx buys count once.
- `scripts/backtest_crawl/` — the free, read-only collectors used overnight (public Solana RPC
  signatures + transactions, DexScreener pair lookup, GeckoTerminal 5m OHLCV).
- `data/baserates.json` — the first real backtest (8-10 Nov 2026; see BRIEF for numbers, coverage and caveats).
  Script flags: `--since` (full-coverage start), `--baseline` (random non-cluster mints for the
  single-wallet buckets, avoids selection bias), `--delay` (copy-lag test), `--priced-only`.
- `sms/grading/baserate.py` — matches an alert to its bucket (cluster size; "+callout-leader" when a
  Pump.fun Callout Rewards leader's wallet is in the cluster) and renders
  "HOW SIMILAR ALERTS TURNED OUT" (or "not enough history yet" below 30 priced signals).
- Holder-structure chip: `sms/sources/safety.py` now reads RugCheck's full report (falls back to
  the summary) and adds `structure` = top-10 share with AMM/pool accounts excluded, linked insider
  wallets, creator share, holders, rugged flag; large values become warnings, never a hidden alert.
- `sms/sources/telegram_public.py` — keyless public Telegram channel reader (`t.me/s/<name>`),
  contract addresses in posts become `Call`s (`tg:<channel>`). Boost-only, like every call.
  Config: `[sources] telegram_channels = [...]`. `Http.get_text` added (same read-only guard).
- `sms/sources/pumpfun_logs.py` — keyless Pump.fun `logsSubscribe` decoder (TradeEvent: mint,
  SOL, tokens, side, trader, ts) matched against the wallet book; reconnects after 60-90 s;
  Helius stays the fallback. PumpSwap pool events not decoded yet.

## Changed
- `sms/stream_worker.py` — (a) after a keepalive ping timeout / no close frame / -32005 "Too many
  subscriptions", wait 60-90 s before resubscribing; (b) forced reconnect after 10 silent minutes
  while subscribed; (c) single-instance fcntl lock (`data/stream_worker.lock`) on top of the pid file.
  The running worker on the box was not touched.
- `sms/wallets.py` — `bot_reason()`: named bots (e.g. "Mayhem Bot" BwWK17…), >10k trades/30d, or
  >500 tx/day get a `bot` tag and are never streamed. (All 14 hits were already reserve wallets, so
  the streamed set stays at 837.)
- `sms/pipeline.py`, `sms/story.py` — every new alert carries `base_rate` and the holder line.
- `sms/report.py` — `stats.by_signal` (live results per signal type) and `baserates` in site.json.
- `web/assets/home.js` — alert cards show the base-rate line and the holder line.
- `web/record.html`, `web/assets/record.js` — new "By signal type" section: live table + backtest table.
- `README.md`, `config.toml` — documented the above.

## Tests
- `tests/test_overnight.py` (19 tests): backtest math, base-rate copy (no advice wording), story
  sections, structure parsing (pools excluded, real RugCheck report), full-report-then-summary
  fallback, Telegram page parsing + address validation, Pump.fun decode from a real captured log,
  bot rule, BwWK17 never streamed, 60-90 s stale wait, silence watchdog, single-instance lock.
- `tests/test_demo_end_to_end.py` — site.json now also has `baserates`.
