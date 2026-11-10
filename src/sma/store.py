"""Local sqlite cache: wallet trades (fetched or observed), narrative history, caller calls."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
create table if not exists trades(chain text, wallet text, token text, side text, ts int, token_amount real,
  value real, value_unit text, price_usd real, tx text, source text, symbol text,
  primary key(chain, wallet, tx, token, side));
create index if not exists trades_w on trades(chain, wallet, ts);
create table if not exists wallet_fetch(chain text, wallet text, source text, fetched_ts int, primary key(chain, wallet));
create table if not exists narrative_hist(ts int, narrative text, score real, vol_h1 real, status text, primary key(ts, narrative));
create table if not exists caller_calls(handle text, chain text, token text, pool text, ts int, price real,
  peak_ratio real, scored int default 0, primary key(handle, chain, token));
"""
COLS = ("chain", "wallet", "token", "side", "ts", "token_amount", "value", "value_unit", "price_usd", "tx", "source", "symbol")


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def add_trades(self, trades):
        rows = [tuple(t.get(c) if c != "symbol" else t.get("symbol", "") for c in COLS) for t in trades
                if t.get("wallet") and t.get("token") and t.get("tx")]
        self.db.executemany(f"insert or ignore into trades values({','.join('?' * len(COLS))})", rows)
        self.db.commit()
        return len(rows)

    def trades(self, chain, wallet, since_ts=0):
        cur = self.db.execute(f"select {','.join(COLS)} from trades where chain=? and wallet=? and ts>=? order by ts",
                              (chain, wallet, since_ts))
        return [dict(zip(COLS, r)) for r in cur.fetchall()]

    def known_txs(self, chain, wallet):
        return {r[0] for r in self.db.execute("select tx from trades where chain=? and wallet=?", (chain, wallet))}

    def fetched(self, chain, wallet):
        r = self.db.execute("select source, fetched_ts from wallet_fetch where chain=? and wallet=?", (chain, wallet)).fetchone()
        return r if r else (None, 0)

    def mark_fetched(self, chain, wallet, source, ts):
        self.db.execute("insert or replace into wallet_fetch values(?,?,?,?)", (chain, wallet, source, int(ts)))
        self.db.commit()

    def narrative_history(self, narrative, before_ts, limit=6):
        return self.db.execute("select score, vol_h1 from narrative_hist where narrative=? and ts<? order by ts desc limit ?",
                               (narrative, before_ts, limit)).fetchall()

    def save_narratives(self, ts, rows):
        self.db.executemany("insert or replace into narrative_hist values(?,?,?,?,?)",
                            [(int(ts), r["narrative"], r["score"], r["vol_h1"], r.get("status")) for r in rows])
        self.db.commit()

    def add_caller_call(self, handle, chain, token, pool, ts, price):
        self.db.execute("insert or ignore into caller_calls(handle, chain, token, pool, ts, price) values(?,?,?,?,?,?)",
                        (handle.lower(), chain, token, pool, int(ts or 0), price))
        self.db.commit()

    def caller_stats(self):
        out = {}
        for h, hits, n in self.db.execute("select handle, sum(case when peak_ratio>=2 then 1 else 0 end), count(*) "
                                          "from caller_calls where scored=1 group by handle"):
            out[h] = (hits or 0, n or 0)
        return out

    def unscored_caller_calls(self, before_ts):
        return self.db.execute("select handle, chain, token, pool, ts, price from caller_calls where scored=0 and ts<=?",
                               (before_ts,)).fetchall()

    def score_caller_call(self, handle, chain, token, peak_ratio):
        self.db.execute("update caller_calls set peak_ratio=?, scored=1 where handle=? and chain=? and token=?",
                        (peak_ratio, handle, chain, token))
        self.db.commit()
