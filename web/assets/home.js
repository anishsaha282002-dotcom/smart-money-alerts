// Home page: ticker, alert story cards, narrative board, wallet leaderboard.
import { $, $$, el, svg, fmt, CHAIN, loadSite, reveal, parallax, hoverTip, tip, badge, statePill, boot, demoBar, fail } from "./app.js";
import { DOODLES, doodle } from "./doodles.js";

const HORIZONS = ["15m", "1h", "4h", "24h"];
const FLAG = { bot: "bot", wash: "wash trading", bundle: "bundler", "fresh-cluster": "fresh cluster", insider: "insider",
  sniper: "sniper", fresh: "new wallet", "one-hit": "one-hit" };
const VERDICT = {
  "mostly-there": "Most of the move was still there 5 minutes later.",
  "partly-gone": "A good part of the move was gone within 5 minutes.",
  "mostly-gone": "Mostly gone within 5 minutes.",
  "never-ran": "The wallet's own buy never got going.",
  unknown: "Not enough price data to say.",
};
const PAGE = 9;
const state = { chain: "all", grade: "all", shown: PAGE };
let site;

boot();
// static, authored illustrations for the hero and the "three grades" cards
$$("[data-doodle]").forEach((n) => { n.innerHTML = DOODLES[n.dataset.doodle] || ""; });
parallax();

loadSite().then((data) => {
  site = data;
  demoBar(site.meta);
  hero();
  ticker();
  filters();
  alerts();
  board();
  wallets();
  reveal();
}).catch((err) => { fail($("#alerts"), err); reveal(); });

// ------------------------------------------------------------------------ hero
function hero() {
  const s = site.stats, hour = s.overall.h["1h"];
  $("#eyebrow-text").textContent = site.meta.demo
    ? `Demo data · ${site.meta.chains.join(" · ")}`
    : `Updated ${fmt.date(site.meta.generated_ts)} · ${site.meta.chains.join(" · ")}`;
  const tiles = [
    [s.alerts, "", "alerts on the public record"],
    [hour.measured ? Math.round(hour.hit_rate * 100) : 0, "%", `above the alert price after 1 hour (${hour.hits} of ${hour.measured})`],
    [s.n_misses, "", `misses, all listed (of ${s.n_measured} measured)`],
    [s.lines, "", "hash-chained ledger lines"],
  ];
  $("#stats").replaceChildren(...tiles.map(([v, suffix, k], i) =>
    el("div", { class: "stat reveal", style: `--i:${i}` },
      el("div", { class: "v num", "data-count": String(v), "data-suffix": suffix, text: "0" + suffix }), el("div", { class: "k", text: k }))));
}

function ago(ts) {
  const d = site.meta.generated_ts - ts;
  return d < 90 ? "just now" : `${fmt.dur(d)} before last update`;
}

function ticker() {
  if (!site.ticker.length) { $("#ticker").hidden = true; return; }
  const items = () => site.ticker.map((t) => el("a", { class: "ticker-item", href: `#${t.id}` },
    badge(t.grade, "wallet"), el("b", { text: t.text }), el("span", { text: ago(t.ts) })));
  // the list twice, so the loop has no seam
  $("#ticker-track").replaceChildren(...items(), ...items().map((n) => { n.setAttribute("aria-hidden", "true"); n.tabIndex = -1; return n; }));
}

// --------------------------------------------------------------------- filters
function filters() {
  const chains = ["all", ...new Set(site.alerts.map((a) => a.chain))];
  const grades = ["all", ...["A", "B", "C", "D"].filter((g) => site.alerts.some((a) => a.grades.wallet.grade === g))];
  const group = (label, key, values, text) => [
    el("span", { class: "lab", text: label }),
    ...values.map((v) => el("button", { class: "seg", type: "button", "aria-pressed": String(state[key] === v),
      text: text(v), onclick: () => { state[key] = v; state.shown = PAGE; filters(); alerts(); reveal(); } })),
  ];
  $("#filters").replaceChildren(
    ...group("Chain", "chain", chains, (v) => v === "all" ? "All" : CHAIN[v] || v),
    el("span", { class: "gap" }),
    ...group("Wallet grade", "grade", grades, (v) => v === "all" ? "All" : v));
}

// ---------------------------------------------------------------- alert cards
function alerts() {
  const list = site.alerts.filter((a) => (state.chain === "all" || a.chain === state.chain)
    && (state.grade === "all" || a.grades.wallet.grade === state.grade));
  const root = $("#alerts");
  if (!list.length) {
    // a live scanner that has not alerted yet is normal, not broken: say why
    const cold = !site.meta.demo && !site.alerts.length;
    root.replaceChildren(el("div", { class: "card empty" },
      el("p", { text: cold ? "The scanner is running. No alert has been sent yet." : "No alerts match these filters yet." }),
      cold ? el("p", { class: "muted", text: `It only alerts when a wallet graded ${site.meta.min_grade} or better buys. `
        + `So far ${site.wallets.length} wallet${site.wallets.length === 1 ? " has" : "s have"} been graded. `
        + "Without a GMGN or Helius key it has to watch wallets for days before it can trust one." }) : null));
    $("#more").replaceChildren();
    return;
  }
  root.replaceChildren(...list.slice(0, state.shown).map((a, i) => card(a, i % 3)));
  $("#more").replaceChildren(list.length > state.shown
    ? el("button", { class: "btn ghost", type: "button", text: `Show ${Math.min(PAGE, list.length - state.shown)} more`,
      onclick: () => { state.shown += PAGE; alerts(); reveal(); } })
    : null);
}

function card(a, i) {
  const w = a.grades.wallet, c = a.grades.caller, n = a.grades.narrative, tok = a.token;
  const who = a.wallet.label || fmt.short(a.wallet.address);
  const where = CHAIN[a.chain] || a.chain;
  const selling = a.activity === "sm_selling";
  const lede = selling
    ? el("p", { class: "lede" }, el("b", { text: who }), ` sold ${fmt.usd(a.buy.usd)}`,
        a.mcap_usd ? ` around a ${fmt.usd(a.mcap_usd)} market cap.` : ".")
    : el("p", { class: "lede" }, el("b", { text: who }), ` put ${fmt.usd(a.buy.usd)} in`,
    a.mcap_usd ? ` at a ${fmt.usd(a.mcap_usd)} market cap` : "",
    a.buy.age_s != null && a.buy.age_s < 86400 ? `, ${fmt.dur(a.buy.age_s)} after launch.` : ".");

  const sample = w.n_closed < 5
    ? el("div", { class: "warn", text: w.n_closed ? `⚠ Tiny sample: only ${w.n_closed} closed trades. Grade capped at C.` : "⚠ No closed trades on record. This grade says almost nothing." })
    : w.small_sample
      ? el("div", { class: "warn", text: `⚠ Small sample: ${w.n_closed} closed trades. Treat the win rate as a rough guide.` })
      : null;
  const cold = w.last10_n >= 8 && w.last10_wins / w.last10_n <= 0.3
    ? el("div", { class: "warn", text: `⚠ Cold streak: only ${w.last10_wins} of its last ${w.last10_n} trades won.` }) : null;
  const flags = (w.flags || []).length
    ? el("div", { class: "danger", text: "⚠ Flags: " + w.flags.map((f) => FLAG[f] || f).join(", ") }) : null;
  const risks = a.safety && a.safety.risks && a.safety.risks.length
    ? el("div", { class: "danger", text: "⚠ Safety: " + a.safety.risks.slice(0, 3).join("; ") }) : null;

  const br = a.base_rate;
  const history = br
    ? el("div", { class: "track history", title: "Measured from the alert price on past alerts of the same kind. Not a forecast." },
        br.enough
          ? `Past alerts like this (${br.label}, n=${br.n}): ${Math.round(br.pct_2x * 100)}% touched 2x within ${br.horizon}, ` +
            `${Math.round(br.pct_down50 * 100)}% fell 50%+. History, not a forecast.`
          : `Not enough history yet for this kind of alert (${br.n} priced).`)
    : null;
  const st = a.safety && a.safety.structure;
  const holders = st
    ? el("div", { class: "track", text: "Holders (RugCheck): " + [
        st.top10_pct != null ? `top 10 own ${Math.round(st.top10_pct)}%` : null,
        st.insiders_detected != null ? `${st.insiders_detected} linked insider wallets` : null,
        st.creator_pct != null ? `creator holds ${st.creator_pct.toFixed(1)}%` : null,
      ].filter(Boolean).join(" · ") || "no holder data" }) : null;

  return el("article", { class: "alert card reveal", id: a.id, style: `--i:${i}` },
    el("header", {},
      el("div", {},
        el("div", { class: "sym", text: `$${tok.symbol || fmt.short(tok.address)}` }),
        el("div", { class: "meta" },
          el("span", { class: selling ? "chip sell" : "chip", text: selling ? "Smart-money selling" : "Smart-money buying" }),
          el("span", { class: "chip", text: where }),
          a.kol ? el("span", { class: "chip", text: "KOL bought" }) : null,
          (a.sm_cluster || []).length >= 2 || (a.cluster || []).length ? el("span", { class: "chip", text: "Wallet cluster bought" }) : null,
          tok.launchpad ? el("span", { class: "chip", text: tok.launchpad }) : null,
          tok.name && tok.name !== tok.symbol ? el("span", { class: "chip", text: tok.name }) : null)),
      el("time", { datetime: new Date(a.ts * 1000).toISOString(), title: fmt.date(a.ts), text: ago(a.ts) })),
    lede,
    el("div", { class: "grades", role: "group", "aria-label": "Three separate grades" },
      badge(w.grade, "Wallet", `${w.score}/100`),
      badge(c.grade, "Callers", c.n_callers ? `${c.n_callers}` : "none yet"),
      el("span", { class: "badge", title: `Narrative: ${n.label}` }, statePill(n.state), el("span", { text: n.key === "other" ? "No clear theme" : n.label }))),
    a.reasons.length ? el("ul", { class: "why" }, a.reasons.map((r) => el("li", { text: r.text }))) : null,
    el("div", { class: "track", text: w.n_closed
      ? `Won ${w.last10_wins} of its last ${w.last10_n} closed trades in ${w.days} days · ${fmt.signedUsd(w.pnl_usd)} realised · ${w.n_closed} closed trades`
      : `No closed trades in the last ${w.days} days.` }),
    sample, cold, flags, risks, history, holders,
    copyBox(a),
    el("div", { class: "outcome", role: "group", "aria-label": "Price after the alert" }, HORIZONS.map((h) => outcome(a, h))),
    el("details", { class: "story" }, el("summary", { text: "Read the full story" }), el("pre", { text: a.story })),
    el("footer", {}, el("span", { class: "mono", text: a.id }), el("a", { href: "record.html#verify", text: "on the public record →" })));
}

function outcome(a, h) {
  const s = a.scores[h];
  let cls = "wait", text = "pending", title = "Not due yet";
  if (s && s.status === "no_data") { text = "no data"; title = "No price data was available for this checkpoint"; }
  else if (s) {
    cls = s.x >= 1 ? "up" : "down";
    text = fmt.pct(s.x);
    title = s.status === "quiet" ? "Nobody traded before this checkpoint: last traded price shown, counted as a miss"
      : `Price vs the alert-time price. Peak ${fmt.pct(s.peak_x)}, low ${fmt.pct(s.low_x)}`;
    if (s.status === "quiet") { cls = "down"; text += " · dead"; }
  }
  return el("div", { class: "out", title }, el("div", { class: "h", text: `+${h}` }), el("div", { class: `x num ${cls}`, text }));
}

// ----------------------------------------------------- "can you still copy it?"
function copyBox(a) {
  const c = a.copy && a.copy.status === "ok" ? a.copy : null, hist = a.copy_hist;
  const box = el("div", { class: "box" }, el("h4", { text: "Can you still copy it?" }));
  if (c) {
    box.append(spark(c, a));
    box.append(el("div", { class: "verdict", text: VERDICT[c.verdict] || "" }));
    const part = (d, label) => c[d]
      ? `${label} later you paid ${fmt.pct(c[d].entry_x)}${c[d].kept != null ? `, ${fmt.share(c[d].kept)} of the upside left` : ""}` : null;
    box.append(el("div", { class: "note", text: [part("5m", "5 min"), part("30m", "30 min")].filter(Boolean).join(" · ") }));
  } else {
    box.append(el("div", { class: "note", text: a.copy
      ? "No price data was available to check this alert."
      : "This alert is checked 4 hours after the buy. Result pending." }));
  }
  if (hist) {
    const k5 = hist["5m"] && hist["5m"].kept, k30 = hist["30m"] && hist["30m"].kept;
    box.append(el("div", { class: "note", text: `This wallet's usual (median of ${hist.n} buys): `
      + (k5 != null ? `${fmt.share(k5)} of the upside left after 5 min, ${fmt.share(k30)} after 30 min.` : "its buys mostly never ran.") }));
  } else if (!c) {
    box.append(el("div", { class: "note", text: "No history yet for this wallet." }));
  }
  box.append(el("div", { class: "note muted", text: "Measured to the 4h peak, so these are best cases." }));
  return box;
}

/** First hour after the wallet's buy, as a multiple of its entry price, with the +5m and +30m copy points. */
function spark(c, a) {
  const W = 320, H = 100, L = 6, R = 58, T = 20, B = 18;
  const pts = c.spark || [];
  const marks = [["5m", 5], ["30m", 30]].filter(([d]) => c[d]).map(([d, m]) => ({ d, m, v: c[d].entry_x }));
  const vals = pts.concat(marks.map((k) => k.v), [1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 0.02) { hi += 0.01; lo -= 0.01; }
  const x = (min) => L + (min / 60) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const step = pts.length > 1 ? 60 / (pts.length - 1) : 60;
  const line = pts.map((v, i) => `${i ? "L" : "M"}${x(i * step).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const sym = a.token.symbol || "coin";

  const root = svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `${sym}: price in the first hour after the wallet's buy. ` + marks.map((k) => `${k.m} minutes later: ${fmt.pct(k.v)}`).join(", ") });
  root.append(
    svg("line", { x1: L, x2: W - R, y1: y(1), y2: y(1), stroke: "var(--ref)", "stroke-width": 1 }),
    // the label sits beside the reference line, kept clear of the axis labels underneath
    svg("text", { x: W - R + 6, y: Math.min(y(1), H - B - 12) }, "wallet's"),
    svg("text", { x: W - R + 6, y: Math.min(y(1), H - B - 12) + 11 }, "entry"));
  if (pts.length > 1) {
    root.append(
      svg("path", { d: `${line}L${x(60).toFixed(1)},${y(lo).toFixed(1)}L${x(0)},${y(lo).toFixed(1)}Z`, fill: "var(--series-wash)" }),
      svg("path", { d: line, fill: "none", stroke: "var(--series)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }
  for (const k of marks) {
    const above = y(k.v) - 9 > 12;
    root.append(
      svg("circle", { cx: x(k.m), cy: y(k.v), r: 4.5, fill: "var(--series)", stroke: "var(--surface-2)", "stroke-width": 2 }),
      svg("text", { x: x(k.m), y: above ? y(k.v) - 9 : y(k.v) + 17, "text-anchor": "middle", style: "fill:var(--ink-2);font-weight:600" },
        `+${k.d} ${fmt.pct(k.v)}`));
  }
  root.append(svg("text", { x: L, y: H - 3 }, "buy"), svg("text", { x: x(60), y: H - 3, "text-anchor": "end" }, "+60 min"));

  // crosshair: the pointer only has to be near a minute, not on the line
  const cross = svg("line", { y1: T - 6, y2: H - B, stroke: "var(--ink-3)", "stroke-width": 1, visibility: "hidden" });
  const dot = svg("circle", { r: 4, fill: "var(--series)", stroke: "var(--surface-2)", "stroke-width": 2, visibility: "hidden" });
  root.append(cross, dot);
  if (pts.length > 1) {
    root.addEventListener("pointermove", (e) => {
      const box = root.getBoundingClientRect();
      const min = Math.max(0, Math.min(60, ((e.clientX - box.left) / box.width * W - L) / (W - L - R) * 60));
      const i = Math.round(min / step);
      cross.setAttribute("x1", x(i * step)); cross.setAttribute("x2", x(i * step)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i * step)); dot.setAttribute("cy", y(pts[i])); dot.setAttribute("visibility", "visible");
      tip.show(e, fmt.pct(pts[i]), [`${Math.round(i * step)} min after the wallet's buy`, "vs the wallet's entry price"]);
    });
    root.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); });
  }
  return root;
}

// ------------------------------------------------------------ narrative board
function board() {
  const root = $("#board");
  if (!site.narratives.length) { root.replaceChildren(el("div", { class: "card empty", text: "No trending data yet." })); return; }
  const top = Math.max(0.01, ...site.narratives.map((n) => Math.max(n.share_now || 0, n.share_base || 0)));
  const row = (label, share, count, ref) => {
    const fill = el("div", { class: `bar-fill ${ref ? "ref" : ""}`, style: "width:0", "data-w": `${(share / top * 100).toFixed(1)}%`, tabindex: "0" });
    hoverTip(fill, () => [fmt.share(share), [`${count} of the coins trending in the ${ref ? "last 24 hours" : "last hour"}`]]);
    return el("div", { class: "bar-row" }, el("span", { text: label }), el("div", { class: "bar-track" }, fill), el("span", { class: "n num", text: fmt.share(share) }));
  };
  root.replaceChildren(...site.narratives.map((n, i) => el("article", { class: "narr card reveal", style: `--i:${i % 4}` },
    el("div", { class: "top" }, doodle(n.key), statePill(n.state)),
    el("h3", { text: n.label }),
    el("div", { class: "bars", role: "group", "aria-label": `${n.label}: share of trending coins` },
      row("Last hour", n.share_now || 0, n.count_now, false), row("Last day", n.share_base || 0, n.count_base, true)),
    n.examples && n.examples.length ? el("div", { class: "eg" }, n.examples.map((s) => el("span", { class: "chip", text: `$${s}` }))) : null,
    n.category_change_24h != null
      ? el("div", { class: "cg", text: `Category market cap ${n.category_change_24h >= 0 ? "+" : ""}${n.category_change_24h.toFixed(1)}% in 24h (CoinGecko)` }) : null)));
}

// ----------------------------------------------------------------- leaderboard
function wallets() {
  const root = $("#wallets");
  if (!site.wallets.length) { root.replaceChildren(el("div", { class: "empty", text: "No wallets graded yet." })); return; }
  const head = ["#", "Wallet", "Grade", "Score", "Closed trades", "Win rate (adjusted)", "Realised", "Typical hold", "Copy check", "Flags"];
  const rows = site.wallets.map((w, i) => {
    const fill = el("div", { class: "bar-fill", style: "width:0", "data-w": `${w.score}%`, tabindex: "0" });
    hoverTip(fill, () => [`${w.score} / 100`, Object.entries(w.parts).map(([k, v]) => `${k.replace("_", " ")} ${v}`)
      .concat(Object.entries(w.penalties).map(([k, v]) => `− ${FLAG[k] || k} ${v}`))]);
    const copy = w.copy && w.copy.verdict ? ({ "mostly-there": "usually still there", "partly-gone": "partly gone", "mostly-gone": "mostly gone", "never-ran": "buys rarely ran" })[w.copy.verdict] : "—";
    return el("tr", { class: "reveal", style: `--i:${Math.min(i, 8)}` },
      el("td", { class: "muted num", text: String(i + 1) }),
      el("td", {}, el("div", { class: "who" }, el("b", { text: w.label || fmt.short(w.wallet) }),
        el("span", { text: `${CHAIN[w.chain] || w.chain} · ${fmt.short(w.wallet)}` }))),
      el("td", {}, badge(w.grade, w.capped ? "capped" : "wallet")),
      el("td", {}, el("div", { class: "score" }, el("span", { class: "num", text: String(w.score) }), el("div", { class: "bar-track" }, fill))),
      el("td", { class: "num", text: w.n_closed ? `${w.wins} of ${w.n_closed} won` : "none" }),
      el("td", { class: "num", text: w.n_closed ? `${fmt.share(w.win_rate_shrunk)}${w.small_sample ? " ⚠" : ""}` : "—",
        title: w.small_sample ? "Small sample" : `Raw win rate ${fmt.share(w.win_rate)}` }),
      el("td", { class: "num", text: fmt.signedUsd(w.pnl_usd) }),
      el("td", { class: "num", text: fmt.dur(w.median_hold_s) }),
      el("td", { text: copy }),
      el("td", {}, el("div", { class: "flags" }, (w.flags || []).map((f) => el("span", { class: `flag ${f === "sniper" || f === "one-hit" || f === "fresh" ? "soft" : ""}`, text: FLAG[f] || f })))));
  });
  root.replaceChildren(el("table", {}, el("thead", {}, el("tr", {}, head.map((h) => el("th", { text: h, scope: "col" })))), el("tbody", {}, rows)));
}
