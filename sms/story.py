"""Turn an alert into a short story a person can read in fifteen seconds.

The default is a fixed template: the same alert always produces the same words, and every number
in it comes straight from the alert. An LLM can optionally reword it (your own key, off by
default), but it is never trusted with the facts: if the reworded text drops or changes a single
number, ticker or grade, the template version is sent instead.
"""
from __future__ import annotations

import logging
import re

from . import ADVICE, DISCLAIMER
from .grading.copycheck import VERDICT_TEXT
from .grading.narrative import STATE_TEXT
from .grading.wallet import FLAG_TEXT
from .models import CHAIN_LABEL, short
from .util import duration, pct, share, signed_usd, usd

log = logging.getLogger(__name__)
GRADE_DOT = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🔴"}


def sample_line(w: dict, cap_below: int = 5) -> str:
    n = w["n_closed"]
    adj = f"{w['win_rate_shrunk'] * 100:.0f}%"
    if n == 0:
        return "⚠ No closed trades on record. This grade says almost nothing."
    if n < cap_below:
        return (f"⚠ Tiny sample: only {n} closed trade{'s' if n != 1 else ''}. "
                f"The grade is capped at C until there are {cap_below}.")
    if w.get("small_sample"):
        return (f"⚠ Small sample: {n} closed trades. Treat the win rate as a rough guide "
                f"(adjusted for sample size it is {adj}).")
    return f"Sample: {n} closed trades (win rate adjusted for sample size: {adj})."


def record_line(w: dict) -> str:
    if not w["n_closed"]:
        return f"No closed trades in the last {w['days']} days."
    hold = f", typical hold {duration(w['median_hold_s'])}" if w.get("median_hold_s") is not None else ""
    return (f"Won {w['last10_wins']} of its last {w['last10_n']} closed trades in {w['days']} days "
            f"({signed_usd(w['pnl_usd'])} realised{hold}).")


def caller_lines(c: dict) -> list[str]:
    lines = []
    for x in (c.get("callers") or [])[:3]:
        if x.get("grade"):
            lines.append(f"• @{x['caller']} — {x['grade']}: coins were {pct(x['median_1h'])} an hour after its calls "
                         f"(median of {x['n_calls']}; {pct(x['median_15m'])} at 15m, {pct(x['median_24h'])} at 24h)")
        else:
            lines.append(f"• @{x['caller']} — unrated ({x['n_calls']} aged call{'s' if x['n_calls'] != 1 else ''})")
    extra = len(c.get("callers") or []) - 3
    if extra > 0:
        lines.append(f"• and {extra} more")
    return lines or [c.get("note") or "No tracked caller has mentioned it yet."]


def narrative_lines(n: dict) -> list[str]:
    if n.get("key") == "other":
        return ["This coin does not fit a tracked theme, so there is no narrative read."]
    line = STATE_TEXT.get(n["state"], n["state"])
    out = [line + "."]
    if n.get("share_now") is not None and n["state"] != "unknown":
        out.append(f"{share(n['share_now'])} of the last hour's trending coins vs {share(n['share_base'])} of the day's.")
    if n.get("posts_now") is not None:
        out.append(f"{n['posts_now']} posts in the last hour (day average {n['posts_base']}/h).")
    return out


def copy_lines(hist: dict | None) -> list[str]:
    if not hist:
        return ["No history yet: this wallet's earlier buys have not been priced.",
                "This alert is checked 5 and 30 minutes after the buy and the result goes on the public record."]
    n = hist["n"]
    head = f"Its last {n} priced buy{'s' if n != 1 else ''}: {VERDICT_TEXT[hist['verdict']]}."
    out = [head]
    d5, d30 = hist.get("5m") or {}, hist.get("30m") or {}
    if d5.get("entry_x") is not None:
        k5 = f", about {share(d5['kept'])} of the upside left" if d5.get("kept") is not None else ""
        out.append(f"• 5 min later you paid {pct(d5['entry_x'])} vs the wallet{k5}.")
    if d30.get("entry_x") is not None:
        k30 = f", about {share(d30['kept'])} of the upside left" if d30.get("kept") is not None else ""
        out.append(f"• 30 min later you paid {pct(d30['entry_x'])} vs the wallet{k30}.")
    if hist["verdict"] in ("mostly-gone", "never-ran"):
        out.append("Honest answer: copying this wallet late has usually not paid.")
    out.append("Measured to the 4h peak, so these are best cases. This alert gets the same check on the record.")
    return out


def render(alert: dict, cap_below: int = 5) -> str:
    tok, w, buy = alert["token"], alert["grades"]["wallet"], alert["buy"]
    c, n = alert["grades"]["caller"], alert["grades"]["narrative"]
    sym = tok["symbol"] or short(tok["address"])
    where = CHAIN_LABEL.get(alert["chain"], alert["chain"]) + (f" · {tok['launchpad']}" if tok.get("launchpad") else "")
    who = alert["wallet"].get("label") or short(alert["wallet"]["address"])
    name = f" ({tok['name']})" if tok.get("name") and tok["name"] != tok["symbol"] else ""

    mcap = f" at a {usd(alert.get('mcap_usd'))} market cap" if alert.get("mcap_usd") else ""
    age = f", {duration(buy['age_s'])} after launch" if buy.get("age_s") is not None and buy["age_s"] < 86400 else ""
    lines = [
        f"{GRADE_DOT.get(w['grade'], '⚪')} {w['grade']}-grade wallet bought ${sym}{name} on {where}",
        f"{who} put {usd(buy['usd'])} in{mcap}{age}.",
        "",
        "WHY THIS ONE",
    ]
    lines += [f"• {r['text']}" for r in alert["reasons"]] or ["• A graded wallet opened a position."]

    lines += ["", f"WALLET GRADE: {w['grade']} ({w['score']}/100)", record_line(w), sample_line(w, cap_below)]
    if w["last10_n"] >= 8 and w["last10_wins"] / w["last10_n"] <= 0.3:
        lines.append(f"⚠ Cold streak: the grade covers {w['days']} days, but only {w['last10_wins']} of its "
                     f"last {w['last10_n']} trades won.")
    flags = [FLAG_TEXT[f] for f in w.get("flags") or [] if f in FLAG_TEXT]
    if flags:
        lines.append("⚠ Flags: " + "; ".join(flags) + ".")
    if w.get("capped") and w["n_closed"] >= cap_below:
        lines.append("The grade is capped at C because of these flags.")

    lines += ["", f"CALLER GRADE: {c['grade'] or 'none yet'}"] + caller_lines(c)
    lines += ["", f"NARRATIVE: {'no clear theme' if n.get('key') == 'other' else n['label']}"] + narrative_lines(n)
    lines += ["", "CAN YOU STILL COPY IT?"] + copy_lines(alert.get("copy_hist"))

    risks = (alert.get("safety") or {}).get("risks") or []
    if risks:
        lines += ["", "⚠ SAFETY: " + "; ".join(risks[:4]) + "."]

    lines += ["", f"Alert {alert['id']}" + (" · SYNTHETIC DEMO DATA" if alert.get("demo") else ""),
              "Not financial advice. This tool cannot trade.",
              ADVICE]
    return "\n".join(lines)


def headline(alert: dict) -> str:
    tok, w = alert["token"], alert["grades"]["wallet"]
    return (f"{w['grade']}-grade wallet bought ${tok['symbol'] or short(tok['address'])} "
            f"on {CHAIN_LABEL.get(alert['chain'], alert['chain'])} · {usd(alert['buy']['usd'])}")


# --------------------------------------------------------------------------- optional LLM rewording

_FACT = re.compile(r"\ba-\d{5}\b"                         # alert id
                   r"|\$\d[\d,]*(?:\.\d+)?[KMB]?"          # money: $2.4K
                   r"|\$[^\s\d,.;:()][^\s,.;:()]*"         # ticker: $WIF, $招财猫
                   r"|[+-]?\d[\d,]*(?:\.\d+)?%?"           # any other number
                   r"|\b[ABCD]\b(?=[\s(:.,-])")           # a grade letter standing alone

REWORD_SYSTEM = (
    "You reword short crypto alert messages so they read naturally. Keep every fact exactly as given: "
    "every number, percentage, dollar amount, ticker, wallet name, grade letter and the alert id must appear "
    "unchanged. Keep the section headings, the warnings (lines starting with ⚠) and the final two lines word for "
    "word. Do not add opinions, predictions, advice or anything not in the original. Reply with the reworded "
    "message only."
)


def facts(text: str) -> list[str]:
    return sorted(_FACT.findall(text))


def facts_preserved(original: str, reworded: str) -> bool:
    """The reworded text carries exactly the same numbers, tickers, grade letters and ids, the
    same number of times. Strict on purpose: swapping two grades keeps the *set* of letters
    intact, so sets are not enough. A false alarm only costs a nicer sentence."""
    return facts(original) == facts(reworded)


def reword(text: str, settings, client=None) -> str:
    """Reword with Claude if the user switched it on and supplied a key; otherwise the text as is."""
    if not (settings.llm_reword and (settings.anthropic_api_key or client is not None)):
        return text
    if client is None and not (settings.llm_model or "").strip():
        log.warning("llm reword skipped: set llm_model in config.toml")
        return text
    try:
        if client is None:
            import anthropic   # optional dependency: pip install "smart-money-stories[llm]"
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.beta.messages.create(
            model=settings.llm_model,
            max_tokens=8000,
            output_config={"effort": "low"},
            # if the model declines, the API re-runs the request on a fallback model in the same call
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=REWORD_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason == "refusal":
            log.warning("llm reword: declined; sending the template")
            return text
        out = next((b.text for b in response.content if b.type == "text"), "").strip()
    except Exception as e:   # noqa: BLE001 - rewording is a nicety: any failure means the template goes out
        log.warning("llm reword failed (%s); sending the template", type(e).__name__)
        return text
    if not out or not facts_preserved(text, out):
        log.warning("llm reword changed a fact; sending the template")
        return text
    if ADVICE not in out or (DISCLAIMER.split(".")[0] not in out and "Not financial advice" not in out):
        return text
    return out
