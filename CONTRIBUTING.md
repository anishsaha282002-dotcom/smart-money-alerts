# Contributing

Thanks for helping. This project has a few rules that are not negotiable, and a few habits that
keep it honest.

## The rules

1. **No trading code. Ever.** No swaps, orders, quotes-for-execution, signing, private keys, seed
   phrases, wallet connections, or libraries whose job is any of those. A pull request that adds
   one will be closed. `tests/test_no_trading.py` enforces this; do not weaken it.
2. **Read-only data sources.** New sources go through `sms/sources/http.py`, which refuses
   anything that looks like a trade. If a legitimate read endpoint is blocked by the guard, add it
   to the allow pattern with a test that shows it is a read.
3. **Every source is optional and fails soft.** A missing key, an outage or a rate limit returns
   nothing and logs one warning. It never stops a scan.
4. **The ledger is append-only.** Nothing may rewrite or delete a line. New facts are new lines.
5. **Free data only.** A source that needs a paid plan must be optional and off by default.
6. **No secrets in the repository.** Keys come from `.env`. Fixtures must not contain real keys.
7. **Permissive licences only.** MIT, Apache-2.0 or BSD code may be adapted with credit in
   `NOTICE.md` and the file header. No unlicensed or AGPL code.

## Honesty habits

- Grades are deterministic. If you change the scoring, say what changed and why in the pull
  request, and update the tables in the README.
- Never blend the three grades into one number.
- Results are measured from the alert-time price. Do not add a metric that uses a price a reader
  could not have had.
- Small samples get a warning, not a confident number.
- Demo data stays labelled as synthetic everywhere it appears.

## Setup

```bash
pip install -e ".[dev]"
```

```bash
pytest -q
```

```bash
sms demo
```

The test suite is offline. Any test that opens a real connection fails by design; use the
`fake_net` fixture and add a JSON file to `tests/fixtures/` instead.

## Adding a data source

1. Write `sms/sources/<name>.py` with pure `parse_*` functions and a small client class that
   takes an `Http`.
2. Save a trimmed real response in `tests/fixtures/` and test the parser against it.
3. Wire it into `sms/sources/hub.py` behind its key, and add it to `status()`.
4. Add the key to `.env.example` and `sms/config.py`, and a row to the README table.
5. Add its URL pattern to `ROUTES` in `tests/conftest.py` so the full-scan test covers it.

## Adding a narrative

Edit `NARRATIVES` in `sms/grading/narrative.py` (English and Chinese keywords), add a case to
`tests/test_caller_narrative_copy.py`, and, if you like drawing, an illustration in
`web/assets/doodles.js`.

## Website

Plain HTML, CSS and JavaScript modules in `web/`. No build step and no third-party scripts or
fonts. Anything that comes from data is inserted with `textContent`, never `innerHTML`.
Check both themes and a phone-width window before opening a pull request.

## Pull requests

- Keep them small and say what you tested.
- New behaviour needs a test.
- `pytest -q` and `sms demo` must pass.
