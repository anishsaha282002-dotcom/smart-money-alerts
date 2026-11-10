// Track-record page: results by grade (misses included), the paper run, and the in-browser ledger verifier.
import { $, el, svg, fmt, CHAIN, loadSite, reveal, parallax, hoverTip, tip, badge, boot, demoBar, fail } from "./app.js";

const HORIZONS = ["15m", "1h", "4h", "24h"];
const GENESIS = "0".repeat(64);
let site, ledgerText = null;

boot();
parallax();
loadSite().then((data) => {
  site = data;
  demoBar(site.meta);
  hero();
  gradeTable($("#by-grade"), site.stats.by_wallet_grade, ["A", "B", "C", "D"], (g) => badge(g, "wallet"), site.stats.overall);
  curve();
  misses();
  gradeTable($("#by-caller"), site.stats.by_caller_grade, Object.keys(site.stats.by_caller_grade),
    (g) => g === "none" ? el("span", { class: "chip", text: "no callers" }) : badge(g, "callers"));
  gradeTable($("#by-state"), site.stats.by_narrative_state, Object.keys(site.stats.by_narrative_state),
    (s) => el("span", { class: `pill ${s}`, text: s === "unknown" ? "quiet" : s }));
  copyVerdicts();
  verifier();
  reveal();
}).catch((err) => { fail($("#by-grade"), err); reveal(); });

function hero() {
  const s = site.stats, hour = s.overall.h["1h"];
  const tiles = [
    [s.alerts, "", "", "alerts sent"],
    [s.n_measured - s.n_misses, "", "", `ended above the alert price (of ${s.n_measured} measured)`],
    [s.n_misses, "", "", "ended below it. All listed further down."],
    [Math.round(hour.paper_pnl), hour.paper_pnl < 0 ? "-$" : "$", "", `paper result: $${s.stake} into every alert, out after 1 hour`],
  ];
  $("#stats").replaceChildren(...tiles.map(([v, prefix, suffix, k], i) =>
    el("div", { class: "stat reveal", style: `--i:${i}` },
      el("div", { class: "v num", "data-count": String(Math.abs(v)), "data-prefix": prefix, "data-suffix": suffix, text: "0" }),
      el("div", { class: "k", text: k }))));
  $("#range").textContent = s.first_ts
    ? `${fmt.day(s.first_ts)} to ${fmt.day(s.last_ts)} · ${s.lines} ledger lines · ${site.meta.demo ? "synthetic demo data" : "live data"}`
    : "No alerts on the record yet.";
}

// --------------------------------------------------------- hit rate by group
/** One row per group, one cell per checkpoint: a thin bar for the hit rate with the counts in text. */
function gradeTable(root, groups, order, label, total) {
  const rows = order.filter((k) => groups[k] && groups[k].n).map((k) => [label(k), groups[k], k]);
  if (total) rows.push([el("b", { text: "All alerts" }), total, "All"]);
  if (!rows.length) { root.replaceChildren(el("div", { class: "empty", text: "Nothing measured yet." })); return; }
  const cell = (row, h, name) => {
    const c = row.h[h];
    if (!c.measured) return el("td", {}, el("span", { class: "muted", text: c.pending ? "pending" : "—" }));
    const fill = el("div", { class: "bar-fill", style: "width:0", "data-w": `${(c.hit_rate * 100).toFixed(1)}%`, tabindex: "0" });
    hoverTip(fill, () => [`${fmt.share(c.hit_rate)} above the alert price`, [
      `${name} · +${h}: ${c.hits} of ${c.measured}`, `median move ${fmt.pct(c.median_x)}`,
      c.quiet ? `${c.quiet} dead (no trades), counted as misses` : null,
      c.pending ? `${c.pending} not due yet` : null, c.no_data ? `${c.no_data} with no price data` : null].filter(Boolean)]);
    return el("td", {}, el("div", { class: "hit" },
      el("div", { class: "t" }, el("b", { class: "num", text: fmt.share(c.hit_rate) }), el("span", { class: "num", text: `${c.hits}/${c.measured}` })),
      el("div", { class: "bar-track" }, fill, el("i", { class: "half" })),
      el("div", { class: "t" }, el("span", { class: "num", text: `median ${fmt.pct(c.median_x)}` }))));
  };
  root.replaceChildren(el("table", {},
    el("thead", {}, el("tr", {}, el("th", { text: "Group", scope: "col" }), el("th", { class: "r", text: "Alerts", scope: "col" }),
      HORIZONS.map((h) => el("th", { text: `+${h}`, scope: "col" })),
      el("th", { class: "r", text: "Hit 2× (24h peak)", scope: "col" }), el("th", { class: "r", text: "Down 80%+", scope: "col" }))),
    el("tbody", {}, rows.map(([lab, row, name]) => el("tr", {},
      el("td", {}, lab), el("td", { class: "r num", text: String(row.n) }),
      HORIZONS.map((h) => cell(row, h, name)),
      el("td", { class: "r num", text: fmt.share(row.reached_2x) }), el("td", { class: "r num", text: fmt.share(row.down_80) }))))));
}

// ------------------------------------------------------------------ paper run
function niceStep(span) {
  const raw = span / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
}

function curve() {
  const pts = site.stats.curve, root = $("#curve");
  if (pts.length < 2) { root.replaceChildren(el("div", { class: "empty", text: "The paper run needs at least two alerts that are an hour old." })); return; }
  const W = 720, H = 300, L = 58, R = 70, T = 16, B = 30;
  const xs = pts.map((p) => p.ts), ys = pts.map((p) => p.total).concat([0]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const step = niceStep(Math.max(...ys) - Math.min(...ys) || 100);
  const lo = Math.floor(Math.min(...ys) / step) * step, hi = Math.ceil(Math.max(...ys) / step) * step;
  const x = (t) => L + (t - x0) / (x1 - x0 || 1) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const money = (v) => (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US");

  const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Running total of a paper run: $${site.stats.stake} into every alert, out one hour later. Ends at ${money(pts[pts.length - 1].total)} after ${pts.length} alerts.` });
  for (let v = lo; v <= hi + 1e-9; v += step) {
    chart.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: Math.abs(v) < 1e-9 ? "var(--ref)" : "var(--grid)", "stroke-width": 1 }),
      svg("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, money(Math.round(v))));
  }
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const t = x0 + (x1 - x0) * i / ticks;
    chart.append(svg("text", { x: x(t), y: H - 8, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" }, fmt.day(t)));
  }
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)},${y(p.total).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  chart.append(
    svg("path", { d: `${d}L${x(x1).toFixed(1)},${y(0).toFixed(1)}L${x(x0).toFixed(1)},${y(0).toFixed(1)}Z`, fill: "var(--series-wash)" }),
    svg("path", { d, fill: "none", stroke: "var(--series)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }),
    svg("circle", { cx: x(last.ts), cy: y(last.total), r: 4.5, fill: "var(--series)", stroke: "var(--surface)", "stroke-width": 2 }),
    svg("text", { x: x(last.ts) + 9, y: y(last.total) + 4, style: "fill:var(--ink);font-weight:650;font-size:13px" }, money(Math.round(last.total))));

  const cross = svg("line", { y1: T, y2: H - B, stroke: "var(--ink-3)", "stroke-width": 1, visibility: "hidden" });
  const dot = svg("circle", { r: 4.5, fill: "var(--series)", stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" });
  chart.append(cross, dot);
  chart.addEventListener("pointermove", (e) => {
    const box = chart.getBoundingClientRect(), px = (e.clientX - box.left) / box.width * W;
    let best = pts[0];
    for (const p of pts) if (Math.abs(x(p.ts) - px) < Math.abs(x(best.ts) - px)) best = p;
    cross.setAttribute("x1", x(best.ts)); cross.setAttribute("x2", x(best.ts)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(best.ts)); dot.setAttribute("cy", y(best.total)); dot.setAttribute("visibility", "visible");
    tip.show(e, money(Math.round(best.total)), [`after alert ${best.id}`, fmt.date(best.ts)]);
  });
  chart.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); });

  const table = el("details", { class: "story" }, el("summary", { text: "View as a table" }),
    el("div", { class: "table-wrap", style: "max-height:260px;overflow:auto;margin-top:10px" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { text: "Alert" }), el("th", { text: "Time" }), el("th", { class: "r", text: "Running total" }))),
      el("tbody", {}, pts.map((p) => el("tr", {}, el("td", { class: "mono", text: p.id }), el("td", { text: fmt.date(p.ts) }),
        el("td", { class: "r num", text: money(Math.round(p.total)) })))))));
  root.replaceChildren(chart, table);
}

// --------------------------------------------------------------------- misses
function misses() {
  const root = $("#misses"), list = site.stats.misses;
  if (!list.length) { root.replaceChildren(el("div", { class: "empty", text: "No misses measured yet. They will be listed here when there are." })); return; }
  const x = (m, h) => {
    const v = m.scores[h];
    if (v == null) return el("td", { class: "r muted", text: m.status[h] === "no_data" ? "no data" : "pending" });
    return el("td", { class: "r num", text: fmt.pct(v) + (m.status[h] === "quiet" ? " · dead" : "") });
  };
  root.replaceChildren(el("table", {},
    el("thead", {}, el("tr", {}, ["Alert", "Coin", "Chain", "Wallet", "Callers", "Narrative"].map((h) => el("th", { text: h, scope: "col" })),
      HORIZONS.map((h) => el("th", { class: "r", text: `+${h}`, scope: "col" })))),
    el("tbody", {}, list.map((m) => el("tr", {},
      el("td", {}, el("a", { class: "mono", href: `index.html#${m.id}`, text: m.id })),
      el("td", {}, el("b", { text: `$${m.symbol}` })), el("td", { text: CHAIN[m.chain] || m.chain }),
      el("td", {}, badge(m.wallet_grade, "wallet")), el("td", {}, badge(m.caller_grade, "callers")),
      el("td", {}, el("span", { class: `pill ${m.state}`, text: m.state === "unknown" ? "quiet" : m.state })),
      HORIZONS.map((h) => x(m, h)))))));
  $("#miss-count").textContent = `${site.stats.n_misses} of ${site.stats.n_measured} measured alerts ended below the alert price. The ${list.length} worst are shown.`;
}

function copyVerdicts() {
  const v = site.stats.copy_verdicts, total = Object.values(v).reduce((a, b) => a + b, 0), root = $("#copy");
  if (!total) { root.replaceChildren(el("div", { class: "empty", text: "No copy checks recorded yet." })); return; }
  const rows = [["mostly-there", "Most of the move still there after 5 min"], ["partly-gone", "A good part gone after 5 min"],
    ["mostly-gone", "Mostly gone after 5 min"], ["never-ran", "The wallet's buy never ran"], ["unknown", "Not enough data"]];
  root.replaceChildren(el("div", { class: "bars" }, rows.filter(([k]) => v[k]).map(([k, label]) => {
    const fill = el("div", { class: "bar-fill", style: "width:0", "data-w": `${(v[k] / total * 100).toFixed(1)}%`, tabindex: "0" });
    hoverTip(fill, () => [`${v[k]} of ${total} alerts`, [label]]);
    return el("div", { class: "bar-row", style: "grid-template-columns:minmax(150px,1.2fr) 1fr 62px" },
      el("span", { text: label }), el("div", { class: "bar-track" }, fill), el("span", { class: "n num", text: `${v[k]} · ${fmt.share(v[k] / total)}` }));
  })));
}

// ------------------------------------------------------------------- verifier
async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** The same rules as sms/ledger.py: every line's `prev` is the SHA-256 of the line before it. */
async function verifyText(text, onProgress) {
  const lines = text.split("\n").filter((l) => l.length);
  const errors = [], bad = new Set();
  let prev = GENESIS;
  for (let i = 0; i < lines.length; i++) {
    let entry = null;
    try { entry = JSON.parse(lines[i]); } catch { errors.push(`line ${i + 1}: not valid JSON`); bad.add(i); }
    if (entry) {
      if (entry.prev !== prev) { errors.push(`line ${i + 1} (seq ${entry.seq}): the line before it was changed, removed or inserted`); bad.add(i); }
      if (entry.seq !== i) { errors.push(`line ${i + 1}: seq is ${entry.seq}, expected ${i}`); bad.add(i); }
    }
    prev = await sha256(lines[i]);
    if (onProgress && i % 25 === 0) onProgress((i + 1) / lines.length);
  }
  if (onProgress) onProgress(1);
  return { ok: !errors.length, lines, head: prev, errors, bad };
}

function verifier() {
  const result = $("#v-result"), bar = $("#v-bar"), list = $("#v-lines");
  $("#v-head").textContent = site.meta.head;

  const show = (v, note) => {
    const published = site.meta.head;
    const headOk = v.head === published;
    result.className = `result ${v.ok && headOk ? "ok" : "bad"}`;
    result.textContent = v.ok && headOk
      ? `✓ ${v.lines.length} lines checked. Every line carries the hash of the one before it, and the last hash matches the published one.`
      : v.ok ? `✗ The chain is consistent but its last hash differs from the published one: lines were added or removed at the end.`
        : `✗ Tampering detected${note ? ` (${note})` : ""}: ${v.errors[0]}${v.errors.length > 1 ? ` (+${v.errors.length - 1} more)` : ""}`;
    const from = Math.max(0, v.lines.length - 60);
    list.replaceChildren(...v.lines.slice(from).map((line, k) => {
      const i = from + k;
      let e = {};
      try { e = JSON.parse(line); } catch { /* shown as broken below */ }
      const what = e.type === "alert" ? `${e.id} $${(e.token || {}).symbol || ""}` : e.type === "score" ? `${e.alert_id} +${e.h} ${e.x == null ? e.status : fmt.pct(e.x)}`
        : e.type === "copy" ? `${e.alert_id} copy check: ${e.verdict || e.status}` : e.type === "anchor" ? `daily anchor ${e.day}` : "";
      return el("div", { class: v.bad.has(i) ? "bad" : "" },
        el("span", { text: String(i).padStart(4, "0") }), el("span", { class: "ty", text: e.type || "?" }),
        el("span", { text: what }), el("span", { class: "muted", text: `prev ${String(e.prev || "").slice(0, 12)}…` }));
    }));
    list.hidden = false;
  };

  const run = async (text, note) => {
    if (!crypto.subtle) { result.className = "result bad"; result.textContent = "This browser cannot hash here. Open the page over https or localhost."; return; }
    result.className = "result"; result.textContent = "Checking…";
    show(await verifyText(text, (p) => { bar.style.width = `${(p * 100).toFixed(0)}%`; }), note);
  };
  const fetchLedger = async () => {
    if (ledgerText == null) {
      const r = await fetch("data/ledger.jsonl", { cache: "no-store" });
      if (!r.ok) throw new Error(`data/ledger.jsonl: HTTP ${r.status}`);
      ledgerText = await r.text();
    }
    return ledgerText;
  };
  const guard = (fn) => async () => {
    try { await fn(); } catch (err) { result.className = "result bad"; result.textContent = `Could not load the ledger: ${err.message}`; }
  };

  $("#v-run").addEventListener("click", guard(async () => run(await fetchLedger())));
  // a demonstration: change one character of one old line, in memory only, and check again
  $("#v-tamper").addEventListener("click", guard(async () => {
    const lines = (await fetchLedger()).split("\n").filter(Boolean);
    const i = Math.max(0, lines.length - 20);
    lines[i] = lines[i].replace(/"ts":(\d+)/, (m, d) => `"ts":${Number(d) + 1}`);
    await run(lines.join("\n"), `this copy had line ${i + 1} edited on purpose`);
  }));
  $("#v-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (file) await run(await file.text(), "from your file");
  });
}
