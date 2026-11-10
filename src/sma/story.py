"""Plain-English alert stories from deterministic templates (no LLM needed).

Optional: set narration.llm: true and LLM_API_KEY to have any OpenAI-compatible endpoint
rewrite the template. The LLM only gets the facts already in the alert and the template is
kept if the call fails or the rewrite drops a number.
"""
from __future__ import annotations

import json
import re

from . import http
from .util import human_dur, human_usd, pct, short

CHAIN_NAME = {"solana": "Solana", "bsc": "BSC", "base": "Base"}


def copy_verdict(late):
    m5 = (late or {}).get("late_5m")
    n = (late or {}).get("late_5m_n") or 0
    if n < 3 or m5 is None:
        return "not enough replayable history to say"
    if m5 >= 0.10:
        return "historically still worth it 5 min late"
    if m5 > 0:
        return "thin edge if you are 5 min late"
    return "historically NOT worth copying 5 min late"


def why_lines(a):
    out = []
    w = a["wallet_grade"]
    if a.get("first_buy_of_token"):
        out.append("first time this wallet has bought this token")
    if a.get("size_vs_median") and a["size_vs_median"] >= 2:
        out.append(f"{a['size_vs_median']:.1f}x its usual buy size")
    co = a.get("cobuyers") or []
    if co:
        g = ", ".join(sorted({c['grade'] for c in co}))
        out.append(f"{len(co)} other graded wallet(s) ({g}) bought it in the last {a.get('lookback_min', 60)}m")
    if a.get("token_age_s") is not None and a["token_age_s"] < 6 * 3600:
        out.append(f"token is only {human_dur(a['token_age_s'])} old")
    n = a.get("narrative") or {}
    if n.get("status") in ("NEW", "RISING", "HOT"):
        out.append(f"its narrative '{n['narrative']}' is {n['status']}")
    if a.get("tracked"):
        out.append("wallet is on your watch list")
    for t in (a.get("tags") or [])[:2]:
        out.append(f"GMGN tag: {t}")
    if not out:
        out.append(f"a grade-{w['grade']} wallet opened a new position")
    return out


def render(a):
    w = a["wallet_grade"]
    late = a.get("late") or {}
    fw = a.get("forward") or {}
    who = a.get("wallet_label") or short(a["wallet"], 4)
    head = (f"SMART-MONEY BUY · ${a.get('symbol') or '?'} on {CHAIN_NAME.get(a['chain'], a['chain'])}"
            f"{' (four.meme)' if a.get('dex') == 'four-meme' or a.get('fourmeme') else ''} · alert #{a['seq_hint']}")
    size = human_usd(a["buy_usd"]) if a.get("buy_usd") else f"{a.get('buy_value', 0):.2f} {a.get('buy_unit', '').upper()}"
    lines = [head,
             f"Wallet {who} — grade {w['grade']} ({w['score']:.0f}/100) bought {size} "
             f"{human_dur(max(0, a['created_ts'] - a['buy_ts']))} ago."]
    rec = f"Record: {w_phrase(w)}"
    if w.get("median_return") is not None:
        rec += f"; median closed trade {pct(w['median_return'])}"
    if w.get("median_hold_s"):
        rec += f", typical hold {human_dur(w['median_hold_s'])}"
    lines.append(rec + f" (n={w['n_closed']} closed, data: {w.get('data_source') or 'n/a'}).")
    for warn in w.get("warnings") or []:
        lines.append(f"⚠ {warn}")
    if w.get("flags"):
        lines.append("⚠ Behaviour flags: " + ", ".join(w["flags"]))
    lines.append("Why it's interesting: " + "; ".join(why_lines(a)) + ".")
    cc = "Can you still copy it? "
    if fw.get("moved_since_buy") is not None:
        cc += f"Price is {pct(fw['moved_since_buy'])} since its buy {fw['minutes_since_buy']:.0f} min ago. "
    if late.get("n"):
        cc += (f"Replaying its last {late['n']} trades: at its price median {pct(late.get('at_buy'))}, "
               f"5 min late {pct(late.get('late_5m'))}, 30 min late {pct(late.get('late_30m'))}")
        if late.get("too_fast_5m"):
            cc += f"; it was already out within 5 min on {late['too_fast_5m']} of them"
        cc += f" — {copy_verdict(late)}."
    else:
        cc += "No replayable history yet (no OHLCV for its past tokens)."
    lines.append(cc)
    c = a.get("caller") or {}
    if not c.get("checked"):
        lines.append(f"Caller chatter: not checked ({c.get('reason', 'X source off')}).")
    elif not c.get("callers"):
        lines.append(f"Caller chatter: grade {c['grade']} — {c['posts']} X posts, none from tracked callers.")
    else:
        def _caller_bit(x):
            if x.get("n_eff", 0) >= 1:
                bit = f"@{x['handle']} ({x['grade']}, {x['rate'] * 100:.0f}% sample-adjusted 2x-rate, n≈{x['n_eff']:.0f}"
            else:
                bit = f"@{x['handle']} (no track record yet"
            if x.get("lb_excluded"):
                bit += "; callout-board boost withheld: flagged wallet"
            elif x.get("lb_factor"):
                bits = (x.get("lb_meta") or {}).get("bits") or []
                detail = "; ".join(bits[:3])
                bit += f"; pump.fun callout leaderboard factor {x['lb_factor']:.2f}" + (f" — {detail}" if detail else "")
            return bit + ")"
        names = ", ".join(_caller_bit(x) for x in c["callers"][:3])
        lines.append(f"Caller chatter: grade {c['grade']} — {len(c['callers'])} tracked caller(s): {names}; {c['posts']} posts total.")
    n = a.get("narrative") or {}
    if n.get("narrative"):
        lines.append(f"Narrative: {n['narrative']} — {n['status']} (momentum {n['score']:.1f}, {n['n_tokens']} tokens, "
                     f"{human_usd(n['vol_h1'])} 1h volume).")
    else:
        lines.append("Narrative: no tracked narrative matched this token.")
    risk = [f"liquidity {human_usd(a.get('liq'))}"]
    if a.get("mcap"):
        risk.append(f"mcap {human_usd(a['mcap'])}")
    lines.append("Risk: " + ", ".join(risk) + ". Prices before fees/slippage. Not financial advice.")
    if a.get("url"):
        lines.append(a["url"])
    return "\n".join(lines)


def w_phrase(w):
    if w["n_closed"] == 0:
        return f"no closed trades in the last {w['window_days']}d"
    s = f"won {w['last10_wins']} of last {w['last10_n']} closed trades over {w['window_days']}d"
    if w["n_closed"] > w["last10_n"]:
        s += f" ({w['wins']}/{w['n_closed']} overall)"
    if w.get("win_rate_shrunk") is not None:
        s += f"; sample-adjusted win rate {w['win_rate_shrunk'] * 100:.0f}%"
    return s


def narrate_llm(text, alert, env):
    """Optional rewrite. Returns the template text on any failure or if numbers were changed."""
    key, base, model = env.get("LLM_API_KEY"), env.get("LLM_BASE_URL") or "https://api.openai.com/v1", env.get("LLM_MODEL") or "gpt-4o-mini"
    if not key:
        return text
    prompt = ("Rewrite this crypto wallet alert as a short, plain-English story (max 120 words) for a retail reader. "
              "Use ONLY these facts, keep every number exactly, keep all warnings, never advise buying, end with "
              "'Not financial advice.'\n\n" + text)
    try:
        r = http.post_json(base.rstrip("/") + "/chat/completions",
                           {"model": model, "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
                           headers={"Authorization": f"Bearer {key}"}, timeout=40, tries=1)
        out = r["choices"][0]["message"]["content"].strip()
    except Exception:
        return text
    nums = set(re.findall(r"[+-]?\d+(?:\.\d+)?%", text))
    if not nums.issubset(set(re.findall(r"[+-]?\d+(?:\.\d+)?%", out))):
        return text          # model dropped or altered a percentage: keep the template
    return out
