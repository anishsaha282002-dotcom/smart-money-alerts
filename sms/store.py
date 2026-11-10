"""Local working memory: a small SQLite file. Not the public record (that is ledger.py).

Holds what the scanner needs between runs: trades it has seen (the only wallet history there
is in keyless mode), caller mentions and how they aged, a key/value cache, and cooldowns.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Call, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
  chain TEXT, wallet TEXT, token TEXT, side TEXT, ts INTEGER, usd REAL, token_amount REAL,
  price_usd REAL, tx TEXT, symbol TEXT, token_created_ts INTEGER, source TEXT,
  PRIMARY KEY(chain, tx, wallet, token, side));
CREATE INDEX IF NOT EXISTS trades_wallet ON trades(chain, wallet, ts);
CREATE INDEX IF NOT EXISTS trades_token ON trades(chain, token, ts);
CREATE TABLE IF NOT EXISTS calls(
  caller TEXT, chain TEXT, token TEXT, ts INTEGER, price_usd REAL, followers INTEGER, text TEXT,
  x15m REAL, x1h REAL, x24h REAL, scored INTEGER DEFAULT 0,
  PRIMARY KEY(caller, chain, token, ts));
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS alerted(chain TEXT, wallet TEXT, token TEXT, ts INTEGER,
  PRIMARY KEY(chain, wallet, token, ts));
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------------------------------------------------------------- trades

    def add_trades(self, trades: list[Trade]) -> int:
        n = 0
        for t in trades:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (t.chain, t.wallet, t.token, t.side, t.ts, t.usd, t.token_amount, t.price_usd,
                 t.tx or f"{t.ts}:{t.usd}", t.symbol, t.token_created_ts, t.source))
            n += cur.rowcount
        self.db.commit()
        return n

    @staticmethod
    def _trade(r: sqlite3.Row) -> Trade:
        return Trade(**{k: r[k] for k in r.keys()})

    def wallet_trades(self, chain: str, wallet: str, since: int = 0, until: int | None = None) -> list[Trade]:
        q = "SELECT * FROM trades WHERE chain=? AND wallet=? AND ts>=?"
        args: list = [chain, wallet, since]
        if until is not None:
            q += " AND ts<=?"
            args.append(until)
        return [self._trade(r) for r in self.db.execute(q + " ORDER BY ts", args)]

    def token_buys(self, chain: str, token: str, since: int, until: int) -> list[Trade]:
        return [self._trade(r) for r in self.db.execute(
            "SELECT * FROM trades WHERE chain=? AND token=? AND side='buy' AND ts>=? AND ts<=? ORDER BY ts",
            (chain, token, since, until))]

    # ----------------------------------------------------------------- calls

    def add_calls(self, calls: list[Call]) -> None:
        for c in calls:
            self.db.execute(
                "INSERT OR IGNORE INTO calls(caller,chain,token,ts,price_usd,followers,text,x15m,x1h,x24h,scored) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (c.caller, c.chain, c.token, c.ts, c.price_usd, c.followers, c.text[:280],
                 c.x15m, c.x1h, c.x24h, int(c.x1h is not None)))
        self.db.commit()

    @staticmethod
    def _call(r: sqlite3.Row) -> Call:
        return Call(caller=r["caller"], chain=r["chain"], token=r["token"], ts=r["ts"], price_usd=r["price_usd"],
                    followers=r["followers"], text=r["text"] or "", x15m=r["x15m"], x1h=r["x1h"], x24h=r["x24h"])

    def calls_for_token(self, chain: str, token: str, until: int) -> list[Call]:
        return [self._call(r) for r in self.db.execute(
            "SELECT * FROM calls WHERE chain=? AND token=? AND ts<=? ORDER BY ts", (chain, token, until))]

    def caller_history(self, caller: str, until: int) -> list[Call]:
        return [self._call(r) for r in self.db.execute(
            "SELECT * FROM calls WHERE caller=? AND ts<=? ORDER BY ts", (caller, until))]

    def unscored_calls(self, before: int, limit: int = 20) -> list[Call]:
        return [self._call(r) for r in self.db.execute(
            "SELECT * FROM calls WHERE scored=0 AND ts<=? ORDER BY ts LIMIT ?", (before, limit))]

    def score_call(self, c: Call) -> None:
        self.db.execute("UPDATE calls SET x15m=?, x1h=?, x24h=?, scored=1 WHERE caller=? AND chain=? AND token=? AND ts=?",
                        (c.x15m, c.x1h, c.x24h, c.caller, c.chain, c.token, c.ts))
        self.db.commit()

    # -------------------------------------------------------------------- kv

    def put(self, key: str, value, ts: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)", (key, json.dumps(value, ensure_ascii=False), ts))
        self.db.commit()

    def get(self, key: str, max_age: int | None = None, now: int | None = None):
        r = self.db.execute("SELECT value, ts FROM kv WHERE key=?", (key,)).fetchone()
        if r is None or (max_age is not None and now is not None and now - r["ts"] > max_age):
            return None
        return json.loads(r["value"])

    def keys(self, prefix: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT key FROM kv WHERE key LIKE ?", (prefix + "%",))]

    # -------------------------------------------------------------- cooldown

    def mark_alerted(self, chain: str, wallet: str, token: str, ts: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO alerted VALUES(?,?,?,?)", (chain, wallet, token, ts))
        self.db.commit()

    def alerted_since(self, chain: str, wallet: str, token: str, since: int) -> bool:
        return self.db.execute("SELECT 1 FROM alerted WHERE chain=? AND wallet=? AND token=? AND ts>=?",
                               (chain, wallet, token, since)).fetchone() is not None
