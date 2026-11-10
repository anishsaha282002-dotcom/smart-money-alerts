# smart-money-alerts

Free, open-source (MIT) **signals-only** tools for memecoin research on Solana and BSC (including four.meme). This repository is the alerts CLI plus the bundled narrative tracker under [`tracker/`](tracker/).

When a tracked wallet buys a memecoin, `sma` can emit one plain-English alert that combines:

1. The wallet's story (grade, recent record, sample-size warning, why this buy is interesting)
2. Wallet, X-caller, and narrative-momentum grades in the same message
3. A "can you still copy it?" check: median gain left if you had bought 5 or 30 minutes late
4. Solana and BSC/four.meme under one English, explanation-first alert
5. A public, hash-chained alert ledger with automatic later scoring

Those five pieces are the gaps a competitor scan found no single free tool filling. See [docs/COMPETITORS.md](docs/COMPETITORS.md) and the longer product notes in [docs/SMA.md](docs/SMA.md). The tracker docs (rules, Helius worker, research) live in [`tracker/`](tracker/).

**Signals only. Not financial advice. There is no trading code** — no buy, sell, swap, order, signing, or private-key handling. An HTTP guard refuses trading and signing endpoints, and tests fail the build if trading code or a trading subcommand appears.

## Quick start

```bash
git clone https://github.com/anishsaha282002-dotcom/smart-money-alerts.git
cd smart-money-alerts
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,stream]"
cp .env.example .env          # optional keys; safe to leave blank

sma demo                      # bundled fixtures; touches no live APIs
# then open demo-out/site/index.html
```

For live Solana wallet tracking, put a free Helius key in `.env`, then run the stream worker and a score pass:

```bash
set -a && source .env && set +a
# Terminal 1 — keep this running (writes tracker/helius_swaps.db)
python tracker/stream_worker.py run

# Terminal 2 — alerts
sma run

# Tracker score (after a plan + extract cycle has produced runs/<RUN>/)
python tracker/tracker.py plan
# …run the printed X queries, then:
python tracker/tracker.py extract --run <RUN>
python tracker/tracker.py score --run <RUN>
```

`sma run` and `tracker.py score` read the worker's SQLite store when its heartbeat is fresh (under two minutes). If the worker is not running they fall back to cheaper Parsed Events polling (~10 credits), not the 100-credit Enhanced history endpoint. No webhook is registered unless you later pass a public HTTPS URL to `python tracker/stream_worker.py register-webhook --url https://...`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `HELIUS_API_KEY` | no | Helius Free plan key for the Parsed Streams worker and the Parsed Events fallback |
| `X_BEARER_TOKEN` | no | Official X API v2 bearer token for caller-chatter grading |
| `GMGN_API_KEY` | no | Optional GMGN Agent API key; GMGN code stays dormant without it. Never set a GMGN private key. |

Optional extras used by some `sma` delivery paths: `HELIUS_STREAM_DB`, `SOLANA_RPC_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. See [docs/SMA.md](docs/SMA.md).

## Tests

```bash
pytest -q
cd tracker && python -m unittest discover -s tests -q
```


## Live calls page

A static site in [`web/`](web/) displays alerts from the public hash-chained ledger as readable cards (coin, chain, BUY/SELL, why, wallet and caller grades, late-copy check, ledger outcomes). It is CDN-free HTML/JS/CSS with no build step.

After `sma run` (or whenever `public/ledger.jsonl` changes), export the public data and open the page locally:

```bash
python3 scripts/export_site_data.py
python3 -m http.server -d web 8080
# then open http://127.0.0.1:8080
```

The exporter writes `web/data/alerts.json` plus caller/wallet summaries from local public files only. It never reads `.env` or copies secrets, and it never invents calls — if the ledger is empty, the page shows a clear "no calls yet" state. Add `?sample=1` to the URL to load labeled example data (`web/data/alerts.sample.json`).

Hosted URL (GitHub Pages): https://anishsaha282002-dotcom.github.io/smart-money-alerts/

A workflow at [`.github/workflows/pages.yml`](.github/workflows/pages.yml) deploys the `web/` folder on every push to `main`. The first time, set the repository's Pages source to **GitHub Actions** in Settings → Pages; the workflow cannot flip that setting by itself.

## License

MIT © 2026 Anish Saha
