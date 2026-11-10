# Third-party notices

Smart Money Stories is MIT licensed. Parts of it are adapted from other MIT projects.
Their copyright notices are kept here and in the headers of the files concerned.

## cvxv666/fomo-robinhood-radar (MIT) — the base

Copyright (c) 2026 fomo-agent contributors
https://github.com/cvxv666/fomo-robinhood-radar

Adapted:

| Our file | Their file | What changed |
|---|---|---|
| `sms/ratelimit.py` | `fomo_agent/ratelimit.py` | Trimmed to the in-process limiter plus a non-blocking `take()` |
| `sms/sources/geckoterminal.py` | `fomo_agent/sources/geckoterminal.py` | Same request/back-off shape; new endpoints (OHLCV, pool trades, four.meme dex) |
| `sms/sources/helius.py` | `fomo_agent/sources/helius.py` | `parse_swap` kept nearly as is; output mapped to our `Trade` |
| `sms/deliver.py` (Telegram part) | `fomo_agent/bot/telegram.py` | Reduced to `sendMessage` with the same 429 handling |
| `sms/report.py` (paper run, verdicts) | `fomo_agent/pipeline/record.py` | Same idea — a fixed stake into every alert, misses kept on the list — over a JSONL ledger instead of SQLite |

Not carried over: the logged-in browser collector for fomo.family, the paid tier and checkout,
and the LLM judge. Grades here are deterministic.

## GMGNAI/gmgn-skills (MIT) — API reference

Copyright (c) 2025 GMGN
https://github.com/GMGNAI/gmgn-skills

`sms/sources/gmgn.py` is a Python port of the **read-only** routes of their OpenAPI client
(endpoint paths, the `X-APIKEY` + `timestamp` + `client_id` auth query, response field names).
The trade, order, strategy, token-creation and signed wallet routes are deliberately not ported,
and are on a blocklist the client refuses to call.

## h100envy/crawl-hive (MIT) — heuristics

Copyright (c) 2026 h100envy
https://github.com/h100envy/crawl-hive

No code copied. Two thresholds in `sms/grading/wallet.py` follow its bundle and sniper scans:
a wallet younger than three days counts as fresh, and a buy within about a second of launch
counts as a snipe.
