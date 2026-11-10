# Backtest collectors (free, read-only)

Used overnight on 10 Nov 2026 to build `data/baserates.json`. No keys. Nothing here signs or sends
a transaction; only `get*` JSON-RPC reads and public GETs.

1. `sigs.py` — signatures per streamed wallet from the public Solana RPC (publicnode keeps about
   1.5-2 days of history).
2. `extend.py <unix_start>` — older signatures from api.mainnet-beta.solana.com (rate-limited, slower).
3. `txs.py [threads]` — `getTransaction` (jsonParsed, v1) for each successful signature; buys and
   sells are read from the wallet's own pre/post token and SOL balances. `EP=` picks the RPC,
   `MAXTS=` limits to older signatures.
4. `prices.py` — needs `targets.json` ({mint: first signal ts}); DexScreener pair lookup, then
   GeckoTerminal pool lookup, then one 5-minute OHLCV request per mint (30/min free limit).
5. `python scripts/backtest_signals.py --db bt.db --priced-only` (merge the `ohlcv` table into the
   same file first).

Set `SMS_WALLETS` to the wallet book path. All output stays local in SQLite files.
