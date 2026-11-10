"""Push the public record and the website data from an always-on server to GitHub.

The server is the only writer of record/ledger.jsonl once it is live (the scheduled GitHub scan
must be switched off then; see deploy/README.md), so the chain never forks. Each publish:

    git add record web/data  ->  commit if anything changed  ->  pull --rebase  ->  push

The GitHub token comes from the environment and is handed to git for one command through an
HTTP header. It is never written to .git/config, a remote URL, or a log line.
"""
from __future__ import annotations

import base64
import re
import subprocess
import time
from pathlib import Path

PATHS = ("record", "web/data")


class PublishError(RuntimeError):
    pass


def _redact(text: str, token: str) -> str:
    text = text or ""
    if token:
        text = text.replace(token, "***")
    return re.sub(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]{10,}", "***", text)


def _git(root: Path, *args: str, token: str = "", check: bool = True) -> str:
    cmd = ["git"]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd += ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    cmd += list(args)
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {_redact(r.stderr.strip() or r.stdout.strip(), token)[:300]}")
    return r.stdout


def publish(settings, branch: str = "smart-money-stories", push: bool = True, root: Path | None = None) -> str:
    root = Path(root or Path(__file__).resolve().parent.parent)
    token = settings.github_token
    if push and not token:
        raise PublishError("GITHUB_TOKEN is not set in .env (see deploy/README.md)")
    present = [p for p in PATHS if (root / p).exists()]
    if not present:
        return "nothing to publish yet"
    _git(root, "add", "--", *present)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode == 0:
        return "no changes since the last publish"
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    _git(root, "-c", "user.name=smart-money-stories-server", "-c", "user.email=server@users.noreply.github.com",
         "commit", "-q", "-m", f"live: {stamp}")
    if not push:
        return f"committed locally ({stamp}); not pushed"
    _git(root, "pull", "-q", "--rebase", "origin", branch, token=token)
    _git(root, "push", "-q", "origin", f"HEAD:{branch}", token=token)
    return f"published {stamp}"
