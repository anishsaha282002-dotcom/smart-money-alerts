// Shared by both pages: data loading, formatting, theme, scroll effects, tooltip, small DOM helpers.
// Everything that comes from data is inserted with textContent, never innerHTML.
import { ROUGH_FILTER } from "./doodles.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
}

const NS = "http://www.w3.org/2000/svg";
export function svg(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) node.append(kid);
  return node;
}

// ------------------------------------------------------------------ formatting
export const fmt = {
  usd(v) {
    if (v == null) return "—";
    const a = Math.abs(v), s = v < 0 ? "-" : "";
    if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
    if (a >= 1e4) return `${s}$${Math.round(a / 1e3)}K`;
    if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`;
    return `${s}$${Math.round(a).toLocaleString("en-US")}`;
  },
  signedUsd(v) { return v == null ? "—" : (v >= 0 ? "+" : "") + fmt.usd(v); },
  pct(x, digits = 0) { return x == null ? "—" : `${x >= 1 ? "+" : ""}${((x - 1) * 100).toFixed(digits)}%`; },
  share(x) { return x == null ? "—" : `${Math.round(x * 100)}%`; },
  dur(s) {
    if (s == null) return "—";
    s = Math.round(s);
    if (s < 90) return `${s}s`;
    if (s < 5400) return `${Math.floor(s / 60)}m`;
    if (s < 172800) { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return m ? `${h}h ${m}m` : `${h}h`; }
    return `${Math.floor(s / 86400)}d`;
  },
  short(a) { return !a ? "" : a.length <= 12 ? a : `${a.slice(0, 6)}…${a.slice(-4)}`; },
  date(ts) { return new Date(ts * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC"; },
  day(ts) { return new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }); },
};
export const CHAIN = { solana: "Solana", bsc: "BNB Chain", base: "Base" };

export async function loadSite() {
  const r = await fetch("data/site.json", { cache: "no-store" });
  if (!r.ok) throw new Error(`data/site.json: HTTP ${r.status}`);
  return r.json();
}

// ----------------------------------------------------------------------- theme
export function initTheme() {
  const btn = $("#theme");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("sms-theme", next); } catch { /* private mode: the choice lasts this visit */ }
  });
}

// ------------------------------------------------------------- scroll effects
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let observer;
export function reveal(root = document) {
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("in");
        $$("[data-count]", e.target).concat(e.target.matches("[data-count]") ? [e.target] : []).forEach(count);
        $$("[data-w]", e.target).forEach((b) => { b.style.width = b.dataset.w; });
        observer.unobserve(e.target);
      }
    }, { threshold: 0.08, rootMargin: "0px 0px -4% 0px" });
  }
  $$(".reveal:not(.in)", root).forEach((n) => observer.observe(n));
}

function count(node) {
  if (node.dataset.done) return;
  node.dataset.done = "1";
  const target = parseFloat(node.dataset.count), suffix = node.dataset.suffix || "", prefix = node.dataset.prefix || "";
  const decimals = (node.dataset.count.split(".")[1] || "").length;
  const show = (v) => {
    node.textContent = prefix + v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
  };
  if (reduced || !isFinite(target)) return show(target);
  const t0 = performance.now(), ms = 1100;
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / ms), eased = 1 - Math.pow(1 - p, 3);
    show(target * eased);
    if (p < 1) requestAnimationFrame(tick); else show(target);
  };
  requestAnimationFrame(tick);
}

export function parallax() {
  if (reduced) return;
  const nodes = $$("[data-parallax]").map((n) => ({ n, f: parseFloat(n.dataset.parallax), rot: n.dataset.rot || "0" }));
  if (!nodes.length) return;
  let ticking = false;
  const run = () => {
    const y = scrollY;
    for (const { n, f, rot } of nodes) n.style.transform = `translate3d(0, ${(y * f).toFixed(1)}px, 0) rotate(${rot}deg)`;
    ticking = false;
  };
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(run); } }, { passive: true });
  run();
}

// --------------------------------------------------------------------- tooltip
let tipNode;
export const tip = {
  show(evt, title, lines = []) {
    if (!tipNode) { tipNode = el("div", { class: "tip", role: "status" }); document.body.append(tipNode); }
    tipNode.replaceChildren(el("b", { text: title }), ...lines.map((l) => el("div", { text: l })));
    tipNode.classList.add("on");
    const pad = 14, w = tipNode.offsetWidth, h = tipNode.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY - h - pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y < 8) y = evt.clientY + pad;
    tipNode.style.left = `${Math.max(8, x)}px`;
    tipNode.style.top = `${y}px`;
  },
  hide() { if (tipNode) tipNode.classList.remove("on"); },
};

/** Hover and keyboard-focus tooltip for one mark. `content` returns [title, lines]. */
export function hoverTip(node, content) {
  node.addEventListener("pointermove", (e) => tip.show(e, ...content()));
  node.addEventListener("pointerleave", tip.hide);
  node.addEventListener("focus", () => {
    const r = node.getBoundingClientRect();
    tip.show({ clientX: r.left + r.width / 2, clientY: r.top }, ...content());
  });
  node.addEventListener("blur", tip.hide);
}

// ------------------------------------------------------------- shared widgets
export function badge(grade, label, small) {
  return el("span", { class: `badge ${grade || ""}`, title: `${label}: ${grade || "not rated"}` },
    el("span", { class: "g" }, el("span", { text: grade || "–" })),
    el("span", { text: label }), small ? el("small", { text: small }) : null);
}
export const statePill = (state) => el("span", { class: `pill ${state}`, text: state === "unknown" ? "quiet" : state });

export function boot() {
  document.body.insertAdjacentHTML("afterbegin", ROUGH_FILTER);   // static filter definition
  initTheme();
}

export function demoBar(meta) {
  if (!meta.demo) return;
  $(".nav").after(el("div", { class: "demo-bar", role: "note",
    text: "You are looking at SYNTHETIC demo data. Wallets, coins and results are generated — they show how the tool works, not how any wallet performs." }));
}

export function fail(target, err) {
  target.replaceChildren(el("div", { class: "card empty" },
    el("p", { text: "No data yet." }),
    el("p", { class: "muted", text: "Run “sms demo” (no keys needed) or “sms run”, then “sms serve”, and reload this page." }),
    el("p", { class: "muted mono", text: String(err.message || err) })));
}
