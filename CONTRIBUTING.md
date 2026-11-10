# Contributing

Thanks for helping. Ground rules:

1. **No trading code, ever.** No swaps, orders, transaction building, signing, wallet
   connections, private keys or seed phrases. `tests/test_safety.py` scans the source and
   fails the build if any of that appears. PRs adding it will be closed.
2. **Free sources only by default.** A new source must work on a free tier or keyless, be
   optional (missing key = skipped, never a crash), have a per-run call budget, and be
   read-only. Paid sources can be added behind an env var but must never be required.
3. **Honest numbers.** Anything shown in an alert must be reproducible from the ledger or the
   documented method. Show sample sizes. Never drop misses from the report.
4. **Don't rewrite the ledger.** `public/ledger.jsonl` is append-only and hash-chained.
   Corrections are new lines, not edits.

## Dev setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q
sma demo
```

`scripts/make_demo_fixtures.py` regenerates the synthetic demo data deterministically
(all wallets, tokens and X handles in it are fictional).

## Adding a data source

Put it in `src/sma/sources/`, route every request through `sma.http` (that's where the
no-trading guard and per-host pacing live), give it `calls`/`errors` attributes and a
budget, wire it into `LiveHub`, and add a parser test with a small real response sample in
`tests/fixtures/`.

## Style

Python 3.11+, stdlib first (only PyYAML is required). Keep functions small and testable.
