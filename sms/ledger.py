"""The public record: an append-only JSONL file where every line carries the hash of the one before.

    line N  = {"seq": N, "type": ..., "ts": ..., ..., "prev": sha256(line N-1)}
    line 0  has prev = 64 zeros

Nothing is ever rewritten. A price check on an old alert is a *new* line that points at it
(`type: "score"`), so the alert stays exactly as it was sent. Changing or deleting any earlier
line changes its hash and breaks the `prev` of the line after it, which `verify()` and the
verifier on the website both report.

The last line has nothing after it to vouch for it. That is what the head hash is for: it is
printed by every report, published with the site, written into the daily `anchor` line, and can
be stamped with OpenTimestamps (`sms anchor`). If the ledger lives in a public git repository,
the commit history is a second witness.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GENESIS = "0" * 64


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def dump(entry: dict) -> str:
    """One canonical line. Insertion order is kept, so the bytes written are the bytes hashed."""
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass
class Verification:
    ok: bool
    lines: int
    head: str
    errors: list[str] = field(default_factory=list)


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: list[dict] | None = None
        self._head: str = GENESIS

    # ------------------------------------------------------------------ read

    def _load(self) -> None:
        self._entries, self._head = [], GENESIS
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").split("\n"):
            if not line:
                continue
            self._entries.append(json.loads(line))
            self._head = line_hash(line)

    def entries(self, type: str | None = None) -> list[dict]:
        if self._entries is None:
            self._load()
        return [e for e in self._entries if type is None or e.get("type") == type]

    @property
    def head(self) -> str:
        if self._entries is None:
            self._load()
        return self._head

    def __len__(self) -> int:
        return len(self.entries())

    # ----------------------------------------------------------------- write

    def append(self, type: str, ts: int, payload: dict) -> dict:
        """Add one line. `seq`, `type`, `ts` and `prev` are set here and cannot be passed in."""
        if self._entries is None:
            self._load()
        for reserved in ("seq", "type", "ts", "prev"):
            if reserved in payload:
                raise ValueError(f"ledger: '{reserved}' is set by the ledger, not the caller")
        entry = {"seq": len(self._entries), "type": type, "ts": int(ts), **payload, "prev": self._head}
        line = dump(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
        self._entries.append(entry)
        self._head = line_hash(line)
        return entry

    def next_alert_id(self) -> str:
        return f"a-{len(self.entries('alert')) + 1:05d}"

    # ---------------------------------------------------------------- verify

    def verify(self) -> Verification:
        return verify_text(self.path.read_text(encoding="utf-8") if self.path.exists() else "")

    # ---------------------------------------------------------------- anchor

    def anchor(self, ts: int, day: str, anchors_dir: Path | None = None) -> dict:
        """Write today's head hash into the chain, and stamp it with OpenTimestamps if the
        `ots` client is installed. Without it the digest file is still written, so it can be
        stamped later or posted anywhere public."""
        head = self.head
        stamped = False
        if anchors_dir is not None:
            anchors_dir.mkdir(parents=True, exist_ok=True)
            digest = anchors_dir / f"{day}.head.txt"
            digest.write_text(head + "\n", encoding="utf-8")
            if shutil.which("ots"):
                try:
                    subprocess.run(["ots", "stamp", str(digest)], check=True, capture_output=True, timeout=60)
                    stamped = True
                except (subprocess.SubprocessError, OSError):
                    stamped = False
        return self.append("anchor", ts, {"day": day, "head": head, "lines": len(self), "ots": stamped})


def verify_text(text: str) -> Verification:
    """Check a ledger given as text. Pure, so the same rules can be tested and mirrored in JS."""
    errors: list[str] = []
    prev = GENESIS
    n = 0
    for i, line in enumerate(text.split("\n")):
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {i + 1}: not valid JSON")
            prev = line_hash(line)
            n += 1
            continue
        if entry.get("prev") != prev:
            errors.append(f"line {i + 1} (seq {entry.get('seq')}): chain broken — "
                          f"the line before it was changed, removed or inserted")
        if entry.get("seq") != n:
            errors.append(f"line {i + 1}: seq is {entry.get('seq')}, expected {n}")
        prev = line_hash(line)
        n += 1
    return Verification(ok=not errors, lines=n, head=prev, errors=errors)
