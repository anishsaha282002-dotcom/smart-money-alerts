// Hand-drawn style illustrations, one per narrative. Static markup written for this project
// (no user data goes in here), drawn with a wobble filter so the lines look inked by hand.
const INK = 'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"';
const wrap = (blob, color, body) =>
  `<svg viewBox="0 0 96 96" aria-hidden="true" focusable="false"><g filter="url(#rough)">` +
  `<path d="${blob}" fill="${color}" opacity=".9"/><g ${INK}>${body}</g></g></svg>`;

export const DOODLES = {
  chinese: wrap("M34 54c0-18 9-26 20-26s20 8 20 26-9 26-20 26-20-8-20-26z", "#ff6b5e",
    `<path d="M30 50c0-16 8-24 18-24s18 8 18 24-8 24-18 24-18-8-18-24z"/><path d="M48 26v48M39 28c-4 14-4 30 0 44M57 28c4 14 4 30 0 44"/>
     <path d="M40 24h16M40 76h16M48 24v-9M48 76v10M44 84l4 7 4-7"/>`),
  ai: wrap("M30 40h42a6 6 0 0 1 6 6v26a6 6 0 0 1-6 6H30a6 6 0 0 1-6-6V46a6 6 0 0 1 6-6z", "#8f8cff",
    `<path d="M27 36h42a6 6 0 0 1 6 6v24a6 6 0 0 1-6 6H27a6 6 0 0 1-6-6V42a6 6 0 0 1 6-6z"/><path d="M48 36V25"/><circle cx="48" cy="21" r="4"/>
     <circle cx="38" cy="51" r="4"/><circle cx="58" cy="51" r="4"/><path d="M40 62c5 3 11 3 16 0M21 50h-6M75 50h6"/>
     <path d="M80 16l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>`),
  animals: wrap("M30 48c0 18 10 30 22 30s22-12 22-30c0-10-44-10-44 0z", "#ffb340",
    `<path d="M26 44c0 18 10 30 22 30s22-12 22-30"/><path d="M26 46l-2-23 15 11M70 46l2-23-15 11M39 34c6-3 12-3 18 0"/>
     <path d="M38 49v5M58 49v5M45 58l3 3 3-3M48 61v3c-3 4-7 2-8 0M48 64c3 4 7 2 8 0"/>
     <path d="M31 60l-12-2M31 64l-12 4M65 60l12-2M65 64l12 4"/>`),
  politics: wrap("M26 46v14l10 2 34 14V28L36 44z", "#5aa9ff",
    `<path d="M22 44v12l10 2 34 12V26L32 42z"/><path d="M32 58l4 16h8l-3-13M74 40c4 4 4 12 0 16M80 34c7 8 7 20 0 28"/>`),
  celebrity: wrap("M52 22l8 18 20 2-15 14 4 20-17-10-17 10 4-20-15-14 20-2z", "#ff7a9c",
    `<path d="M48 18l8 18 20 2-15 14 4 20-17-10-17 10 4-20-15-14 20-2z"/>
     <path d="M35 45h11v5a5.500 5.500 0 0 1-11 0zM50 45h11v5a5.500 5.500 0 0 1-11 0zM46 46h4M42 60c4 3 8 3 12 0"/>`),
  binance: wrap("M52 26a26 26 0 1 0 .1 0z", "#ffd84d",
    `<circle cx="48" cy="48" r="26"/><path d="M48 31l17 17-17 17-17-17z"/><path d="M48 41l7 7-7 7-7-7z"/><path d="M80 20l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>`),
  gaming: wrap("M34 40h36c8 0 12 8 12 18s-4 14-9 14-7-8-12-8H43c-5 0-7 8-12 8s-9-4-9-14 4-18 12-18z", "#58e07f",
    `<path d="M30 36h36c8 0 12 8 12 18s-4 14-9 14-7-8-12-8H39c-5 0-7 8-12 8s-9-4-9-14 4-18 12-18z"/>
     <path d="M32 50h11M37.500 44.500v11"/><circle cx="60" cy="47" r="2.600"/><circle cx="67" cy="54" r="2.600"/>`),
  food: wrap("M26 54h52c0 14-10 24-26 24S26 68 26 54z", "#ffa64d",
    `<path d="M22 50h52c0 14-10 24-26 24S22 64 22 50z"/><path d="M34 50c0-9 4-10 4-19M46 50c0-11 4-12 4-23M58 50c0-9 4-10 4-19"/><path d="M62 20l18 26M68 18l16 25"/>`),
  stocks: wrap("M28 40h10v22H28zM46 32h10v26H46zM64 46h10v20H64z", "#6fd6ff",
    `<path d="M30 28v44M25 37h10v22H25zM48 20v48M43 29h10v26H43zM66 32v44M61 43h10v20H61z"/>`),
  other: wrap("M52 24l6 20 20 8-20 8-6 20-6-20-20-8 20-8z", "#c98bff",
    `<path d="M48 20l6 20 20 8-20 8-6 20-6-20-20-8 20-8z"/><path d="M78 18l2 5 5 2-5 2-2 5-2-5-5-2 5-2zM20 66l1.500 4 4 1.500-4 1.500-1.500 4-1.500-4-4-1.500 4-1.500z"/>`),
  wallet: wrap("M24 38h48a6 6 0 0 1 6 6v26a6 6 0 0 1-6 6H24a6 6 0 0 1-6-6V44a6 6 0 0 1 6-6z", "#7ee0a1",
    `<path d="M20 34h48a6 6 0 0 1 6 6v26a6 6 0 0 1-6 6H20a6 6 0 0 1-6-6V40a6 6 0 0 1 6-6z"/><path d="M20 34l36-12 4 12M58 48h16v12H58a6 6 0 0 1 0-12z"/><circle cx="61" cy="54" r="1.600"/>`),
  caller: wrap("M30 34h44a6 6 0 0 1 6 6v20a6 6 0 0 1-6 6H52l-12 10V66h-10a6 6 0 0 1-6-6V40a6 6 0 0 1 6-6z", "#7cc4ff",
    `<path d="M26 30h44a6 6 0 0 1 6 6v20a6 6 0 0 1-6 6H48L36 72V62H26a6 6 0 0 1-6-6V36a6 6 0 0 1 6-6z"/><path d="M34 42h28M34 50h18"/>`),
  wave: wrap("M18 62c10-22 18 12 30-10s18 12 30-10v34H18z", "#ffb3c7",
    `<path d="M14 58c10-22 18 12 30-10s18 12 30-10"/><path d="M66 30l10 6-4 10"/>`),
  chain: wrap("M30 34h18v18H30zM52 46h18v18H52z", "#d7a6ff",
    `<path d="M26 30h18v18H26zM48 42h18v18H48zM70 54h12v18H70M44 39h8M66 51h8M30 36h10M30 42h7M52 48h10M52 54h7"/>`),
};

export const ROUGH_FILTER =
  `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><filter id="rough" x="-10%" y="-10%" width="120%" height="120%">` +
  `<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7" result="n"/>` +
  `<feDisplacementMap in="SourceGraphic" in2="n" scale="2.6" xChannelSelector="R" yChannelSelector="G"/></filter></defs></svg>`;

export function doodle(key) {
  const d = document.createElement("div");
  d.className = "doodle";
  d.innerHTML = DOODLES[key] || DOODLES.other;      // static, authored markup only
  return d;
}
