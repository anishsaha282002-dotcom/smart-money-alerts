# Smart-money-alerts — live calls web page (additive update)

Apply these files on top of `main`. Do **not** overwrite or reset `tracker/smart_wallets.json`, `tracker/stream_worker.py`, `tracker/callers.json`, or other files being updated by concurrent jobs. This package only adds a static calls site, an exporter, a Pages workflow, one test file, and a short README section.

## What this is

There was no browser front-end for live calls (only `sma report` HTML in `public/` after a run, and an empty `public/README.md`). This adds a CDN-free static site in `web/` that reads `data/alerts.json` and shows calls as cards.

## Files in this package (paths relative to repo root)

- `web/index.html`, `web/app.js`, `web/style.css`, `web/.nojekyll` — the site
- `web/data/alerts.json` — exported from the real local ledger; **currently empty** (no real alerts exist yet; do not invent any)
- `web/data/alerts.sample.json` — labeled EXAMPLE data from bundled demo fixtures; the UI loads it only with `?sample=1` and shows an example-data banner
- `web/data/callers.json`, `web/data/wallets.json` — public summaries from `data/callers.json` (54 callers, 5 flagged, 3 catalysts) and `data/wallets.json` (10 wallets)
- `scripts/export_site_data.py` — writes the files above from `public/ledger.jsonl` + `data/callers.json` + `data/wallets.json`. Never reads `.env` or copies secrets. Skips `demo: true` ledger rows in `alerts.json`.
- `.github/workflows/pages.yml` — deploys `web/` to GitHub Pages (`actions/configure-pages`, `upload-pages-artifact`, `deploy-pages`; permissions `pages: write`, `id-token: write`). Re-runs the exporter first so a committed ledger is reflected.
- `tests/test_export_site_data.py` — exporter unit tests (empty ledger, demo exclusion, mapping, secret stripping, sample flag)
- `README.md` — **additive** "Live calls page" section only (insert before License). Do not replace the rest of the file if `main` has moved on; merge the section.
- `CHANGES-web.md` — this file

## After applying

1. Re-scan these files for secrets (no API keys, no `.env`, no Helius key).
2. Run tests: `pytest -q` and `cd tracker && python -m unittest discover -s tests -q`.
3. Push to `main` or open a PR. Do not include unrelated tracker edits from other jobs in the same commit unless those jobs are also ready.
4. First-time Pages setup: in the GitHub repo, Settings → Pages → source **GitHub Actions**. The workflow cannot flip that setting itself.

Expected Pages URL: https://anishsaha282002-dotcom.github.io/smart-money-alerts/

Local preview:

```bash
python3 scripts/export_site_data.py
python3 -m http.server -d web 8080
# http://127.0.0.1:8080
```

## Data status at export time (2026-11-10)

- No `public/ledger.jsonl` in the publish tree. Memecoin-tracker `state.db` had 59 snapshots, all `REJECT` (zero BUY/SELL). The only ledger on disk was demo-out (synthetic). `alerts.json` is therefore empty; the page shows "No calls yet".
