"""Static report (HTML + Markdown) from the public ledger. Every alert is listed - misses included."""
from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path

from .ledger import Ledger, verify
from .util import median, pct, short, utc_iso

HZ = ("15m", "1h", "4h", "24h")


def _rows(ledger):
    scores = ledger.scores()
    rows = []
    for a in ledger.alerts():
        s = scores.get(a["id"], {})
        rows.append({"a": a, "s": s})
    return rows


def _group_stats(rows, keyf):
    g = defaultdict(list)
    for r in rows:
        g[keyf(r) or "n/a"].append(r)
    out = []
    for k in sorted(g):
        rs = g[k]
        line = {"group": k, "alerts": len(rs)}
        for h in ("1h", "24h"):
            vals = [r["s"][h]["ret_from_alert"] for r in rs if h in r["s"] and r["s"][h].get("ret_from_alert") is not None]
            line[f"n_{h}"] = len(vals)
            line[f"win_{h}"] = (sum(v > 0 for v in vals) / len(vals)) if vals else None
            line[f"med_{h}"] = median(vals)
        l5 = [r["s"]["24h"]["ret_if_5m_late"] for r in rs if "24h" in r["s"] and r["s"]["24h"].get("ret_if_5m_late") is not None]
        l30 = [r["s"]["24h"]["ret_if_30m_late"] for r in rs if "24h" in r["s"] and r["s"]["24h"].get("ret_if_30m_late") is not None]
        line["med_late5_24h"], line["med_late30_24h"] = median(l5), median(l30)
        out.append(line)
    return out


GROUPS = {
    "Wallet grade": lambda r: r["a"]["wallet_grade"]["grade"],
    "Caller grade": lambda r: (r["a"]["caller"].get("grade") or "not checked") if r["a"].get("caller") else "not checked",
    "Narrative status": lambda r: (r["a"].get("narrative") or {}).get("status") or "none",
    "Chain": lambda r: r["a"]["chain"],
}


def build(cfg, out_dir, now_ts):
    from .config import resolve
    lp = resolve(cfg, "ledger")
    ledger = Ledger(lp)
    ok, n, head, problems = verify(lp)
    rows = _rows(ledger)
    demo = any(r["a"].get("demo") for r in rows)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.head.txt").write_text(f"{head}  lines={n}  generated={utc_iso(now_ts)}\n")

    md = ["# Smart-money alert ledger — performance report", "",
          f"Generated {utc_iso(now_ts)} UTC. Ledger: `{lp.name}`, {n} lines, head sha256 `{head}`, "
          f"chain check: **{'OK' if ok else 'BROKEN'}**.", ""]
    if demo:
        md += ["> **DEMO DATA** — these alerts come from bundled synthetic fixtures, not live markets.", ""]
    md += ["Returns are price changes from the alert price (before fees/slippage). `late5`/`late30` = return at +24h if you",
           "had bought 5/30 minutes after the wallet. Win = return > 0. Unscored horizons are not yet due.", ""]
    for title, f in GROUPS.items():
        md += [f"## By {title.lower()}", "", "| group | alerts | 1h n | 1h win | 1h median | 24h n | 24h win | 24h median | late5 24h | late30 24h |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for s in _group_stats(rows, f):
            md.append(f"| {s['group']} | {s['alerts']} | {s['n_1h']} | {pct(s['win_1h'])[1:] if s['win_1h'] is not None else 'n/a'} | "
                      f"{pct(s['med_1h'])} | {s['n_24h']} | {pct(s['win_24h'])[1:] if s['win_24h'] is not None else 'n/a'} | "
                      f"{pct(s['med_24h'])} | {pct(s['med_late5_24h'])} | {pct(s['med_late30_24h'])} |")
        md.append("")
    md += ["## Every alert (misses included)", "",
           "| # | time (UTC) | chain | token | wallet | W | C | narrative | " + " | ".join(HZ) + " | max 24h |",
           "|---|---|---|---|---|---|---|---|" + "---|" * len(HZ) + "---|"]
    for r in rows:
        a, s = r["a"], r["s"]
        cells = [pct(s[h]["ret_from_alert"]) if h in s else "…" for h in HZ]
        mx = pct(s["24h"]["max_ret_from_alert"]) if "24h" in s else "…"
        md.append(f"| {a['seq']} | {a['created'][:16].replace('T', ' ')} | {a['chain']} | ${a.get('symbol') or '?'} | "
                  f"`{short(a['wallet'])}` | {a['wallet_grade']['grade']} | {(a.get('caller') or {}).get('grade') or '–'} | "
                  f"{((a.get('narrative') or {}).get('narrative') or '–')} {((a.get('narrative') or {}).get('status') or '')} | "
                  + " | ".join(cells) + f" | {mx} |")
    md += ["", "## Verify it yourself", "", "```bash", f"sma verify-ledger --ledger {lp.name}",
           "# or without this tool: each line's \"prev\" must equal sha256 of the previous line's bytes",
           "python3 -c \"import hashlib,json,sys;p='0'*64\nfor l in open(sys.argv[1]):\n l=l.rstrip('\\n');assert json.loads(l)['prev']==p;p=hashlib.sha256(l.encode()).hexdigest()\nprint('ok',p)\" " + lp.name,
           "```", ""]
    if problems:
        md += ["## Ledger problems", ""] + [f"- {p}" for p in problems]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")
    (out / "index.html").write_text(_html(md, demo), encoding="utf-8")
    return out / "index.html", ok


def _html(md_lines, demo):
    body, in_table, in_code = [], False, False
    for ln in md_lines:
        if ln.startswith("```"):
            body.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(ln))
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(set(c) <= {"-"} for c in cells):
                continue
            if not in_table:
                body.append("<table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                tds = []
                for c in cells:
                    cls = "neg" if c.startswith("-") and c.endswith("%") else "pos" if c.startswith("+") else ""
                    tds.append(f"<td class='{cls}'>{html.escape(c.strip('`'))}</td>")
                body.append("<tr>" + "".join(tds) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if ln.startswith("# "):
            body.append(f"<h1>{html.escape(ln[2:])}</h1>")
        elif ln.startswith("## "):
            body.append(f"<h2>{html.escape(ln[3:])}</h2>")
        elif ln.startswith("> "):
            body.append(f"<p class='demo'>{html.escape(ln[2:].replace('**', ''))}</p>")
        elif ln.startswith("- "):
            body.append(f"<li>{html.escape(ln[2:])}</li>")
        elif ln.strip():
            body.append(f"<p>{html.escape(ln).replace('**', '')}</p>")
    if in_table:
        body.append("</table>")
    css = ("body{font:14px/1.45 system-ui,sans-serif;max-width:1200px;margin:2em auto;padding:0 1em;color:#111}"
           "table{border-collapse:collapse;margin:.5em 0 1.5em;font-size:13px}th,td{border:1px solid #ddd;padding:4px 8px;text-align:left}"
           "th{background:#f4f4f4}.pos{color:#0a7d32}.neg{color:#b00020}.demo{background:#fff3cd;padding:.6em;border-radius:6px}"
           "pre{background:#f6f8fa;padding:1em;overflow:auto}")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Smart-money alert ledger</title><style>{css}</style></head><body>" + "\n".join(body) +
            "<p><a href='ledger.jsonl'>ledger.jsonl</a> · <a href='ledger.head.txt'>head hash</a> · "
            "<a href='report.md'>markdown</a></p><p>Not financial advice. Research tool; it never trades.</p></body></html>")
