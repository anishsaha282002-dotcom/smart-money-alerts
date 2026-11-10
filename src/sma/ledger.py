"""Append-only, hash-chained JSONL alert ledger.

Every line is a compact JSON object with sorted keys and a ``prev`` field holding the
sha256 of the *previous line's exact bytes* (64 zeros for the first line). Alerts and their
later scores are separate lines, so nothing is ever rewritten. Editing, deleting or
reordering any past line breaks every following ``prev`` and ``sma verify-ledger`` reports
the first bad line. Publish the head hash (or anchor it with OpenTimestamps) and anyone
can check that history was not rewritten afterwards.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

GENESIS = "0" * 64


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _dump(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def lines(self):
        if not self.path.exists():
            return []
        return [ln for ln in self.path.read_text(encoding="utf-8").split("\n") if ln.strip()]

    def records(self):
        return [json.loads(ln) for ln in self.lines()]

    def head(self):
        ls = self.lines()
        return (line_hash(ls[-1]), len(ls)) if ls else (GENESIS, 0)

    def append(self, record: dict) -> dict:
        prev, seq = self.head()
        rec = {k: v for k, v in record.items() if k not in ("prev", "seq")}
        rec["prev"], rec["seq"] = prev, seq
        line = _dump(rec)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        rec["hash"] = line_hash(line)
        return rec

    def alerts(self):
        return [r for r in self.records() if r.get("type") == "alert"]

    def scores(self):
        out = {}
        for r in self.records():
            if r.get("type") == "score":
                out.setdefault(r["alert_id"], {})[r["horizon"]] = r
        return out


def verify(path):
    """Return (ok, n_lines, head_hash, problems)."""
    p = Path(path)
    if not p.exists():
        return True, 0, GENESIS, []
    raw = p.read_text(encoding="utf-8")
    problems = []
    if raw and not raw.endswith("\n"):
        problems.append("file does not end with a newline (truncated write?)")
    ls = [ln for ln in raw.split("\n") if ln.strip()]
    prev = GENESIS
    for i, ln in enumerate(ls):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            problems.append(f"line {i + 1}: not valid JSON")
            prev = line_hash(ln)
            continue
        if obj.get("prev") != prev:
            problems.append(f"line {i + 1}: prev hash mismatch (line edited, removed or reordered at or before here)")
        if obj.get("seq") != i:
            problems.append(f"line {i + 1}: seq {obj.get('seq')} != {i}")
        if _dump(obj) != ln:
            problems.append(f"line {i + 1}: not in canonical form (re-serialized or hand-edited)")
        prev = line_hash(ln)
    return (not problems), len(ls), prev, problems
