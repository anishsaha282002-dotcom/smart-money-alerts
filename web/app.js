(function () {
  "use strict";

  var REFRESH_MS = 60000;
  var TZ = "America/Chicago";
  var params = new URLSearchParams(window.location.search);
  var useSample = params.get("sample") === "1";
  var alertsUrl = useSample ? "data/alerts.sample.json" : "data/alerts.json";
  var state = { data: null, callers: null, wallets: null, error: null, loadedAt: null };
  var timer = null;

  var $ = function (id) { return document.getElementById(id); };

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function shortAddr(addr, n) {
    n = n || 4;
    if (!addr) return "—";
    var s = String(addr);
    if (s.length <= n * 2 + 1) return s;
    return s.slice(0, n) + "…" + s.slice(-n);
  }

  function pct(v) {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "n/a";
    var n = Number(v) * 100;
    var sign = n > 0 ? "+" : "";
    var rounded = Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(1);
    if (Object.is(Number(rounded), -0) || rounded === "0.0" || rounded === "0" || rounded === "-0.0" || rounded === "-0") {
      return "0%";
    }
    return sign + rounded + "%";
  }

  function pctClass(v) {
    if (v == null || Number.isNaN(Number(v))) return "";
    if (Number(v) > 0) return "pos";
    if (Number(v) < 0) return "neg";
    return "";
  }

  function formatCst(iso) {
    if (!iso) return "time unknown";
    var d = new Date(iso);
    if (isNaN(d.getTime()) && typeof iso === "number") d = new Date(iso * 1000);
    if (isNaN(d.getTime())) return escapeHtml(String(iso));
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZoneName: "short"
    }).formatToParts(d);
    var get = function (t) {
      var row = parts.find(function (p) { return p.type === t; });
      return row ? row.value : "";
    };
    var zone = get("timeZoneName") || "CST";
    return get("weekday") + " " + get("month") + " " + get("day") + ", " + get("year") + ", " +
      get("hour") + ":" + get("minute") + " " + get("dayPeriod") + " " + zone;
  }

  function formatUpdated(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return "Exported " + formatCst(iso);
  }

  function chainLabel(chain) {
    var c = String(chain || "").toLowerCase();
    if (c === "bsc") return "BSC";
    if (c === "solana") return "Solana";
    if (c === "base") return "Base";
    return chain || "unknown";
  }

  function letterSpan(grade) {
    var g = (grade || "–").toString();
    return '<span class="letter ' + escapeHtml(g.charAt(0)) + '">' + escapeHtml(g) + "</span>";
  }

  function pill(cls, text) {
    return '<span class="pill ' + cls + '">' + escapeHtml(text) + "</span>";
  }

  function renderCard(a) {
    var decision = (a.decision || "BUY").toUpperCase();
    var pills = [
      pill(decision === "SELL" ? "sell" : "buy", decision),
      pill("chain", chainLabel(a.chain) + (a.dex === "four-meme" ? " · four.meme" : ""))
    ];
    if (a.sm_confirmed) pills.push(pill("sm", "Smart-money confirmed"));
    if (a.kol_buy) pills.push(pill("kol", "KOL buy"));
    if (a.narrative && a.narrative.status) {
      pills.push(pill("", (a.narrative.narrative || "narrative") + " · " + a.narrative.status));
    }

    var explorers = a.explorers || {};
    var mintLinks = [];
    if (a.token) {
      mintLinks.push(
        '<span class="addr" title="' + escapeHtml(a.token) + '">' + escapeHtml(shortAddr(a.token, 4)) + "</span>"
      );
      if (explorers.dexscreener) {
        mintLinks.push('<a href="' + escapeHtml(explorers.dexscreener) + '" target="_blank" rel="noopener noreferrer">DexScreener</a>');
      }
      if (explorers.scan) {
        mintLinks.push('<a href="' + escapeHtml(explorers.scan) + '" target="_blank" rel="noopener noreferrer">' +
          escapeHtml(explorers.scan_label || "Explorer") + "</a>");
      }
    }

    var why = (a.why && a.why.length) ? a.why.join("; ") : "";
    var wallet = a.wallet || {};
    var cobuyers = a.cobuyers || [];
    var cobuyerBits = cobuyers.map(function (c) {
      return letterSpan(c.grade) + ' <span class="addr">' + escapeHtml(shortAddr(c.address || c.wallet, 4)) + "</span>";
    }).join(", ");
    var scoreBit = wallet.score != null ? " (" + Math.round(Number(wallet.score)) + "/100)" : "";
    var walletName = wallet.label || shortAddr(wallet.address, 4);
    var wr = wallet.win_rate_shrunk != null ? " · adj. win rate " + pct(wallet.win_rate_shrunk) : "";

    var caller = a.caller || {};
    var callerBody;
    if (!caller.checked) {
      callerBody = '<p class="sub">Not checked' + (caller.reason ? " (" + escapeHtml(caller.reason) + ")" : "") + ".</p>";
    } else if (!(caller.callers && caller.callers.length)) {
      callerBody = '<p class="sub">' + (caller.posts != null ? escapeHtml(String(caller.posts)) + " posts, " : "") +
        "none from tracked callers.</p>";
    } else {
      callerBody = '<p class="sub">' + caller.callers.map(function (c) {
        return "@" + escapeHtml(c.handle || "?") + " " + letterSpan(c.grade);
      }).join(" · ") + "</p>";
    }

    var lateHtml = "";
    if (a.late && (a.late.late_5m != null || a.late.late_30m != null || a.late.n)) {
      lateHtml = '<div class="checks"><p><strong>Late-copy check</strong> · 5 min ' +
        '<span class="' + pctClass(a.late.late_5m) + '">' + pct(a.late.late_5m) + "</span>" +
        " · 30 min " +
        '<span class="' + pctClass(a.late.late_30m) + '">' + pct(a.late.late_30m) + "</span>" +
        (a.late.n ? ' <span class="faint">(n=' + escapeHtml(String(a.late.n)) + ")</span>" : "") +
        (a.late.verdict ? " — " + escapeHtml(a.late.verdict) : "") +
        "</p></div>";
    }

    var outHtml = "";
    if (a.outcomes) {
      var keys = ["15m", "1h", "4h", "24h"].filter(function (h) { return a.outcomes[h]; });
      if (keys.length) {
        outHtml = '<div class="checks"><p><strong>Ledger outcome</strong> · ' +
          keys.map(function (h) {
            var r = a.outcomes[h].ret_from_alert;
            return escapeHtml(h) + ' <span class="' + pctClass(r) + '">' + pct(r) + "</span>";
          }).join(" · ") +
          "</p></div>";
      }
    }

    var narrHtml = "";
    if (a.narrative && a.narrative.narrative) {
      var st = a.narrative.status || "";
      var hot = /^(HOT|RISING|NEW)$/.test(st) ? "hot" : "";
      narrHtml = '<p class="narr">Narrative: ' + escapeHtml(a.narrative.narrative) +
        ' — <span class="' + hot + '">' + escapeHtml(st) + "</span></p>";
    }

    var storyId = "story-" + escapeHtml(a.id || String(a.seq || ""));
    var storyBlock = a.text
      ? '<p class="sub" style="margin-top:.7rem"><button class="linkish" type="button" data-toggle="' +
        storyId + '">Show full description</button></p>' +
        '<pre class="story" id="' + storyId + '" hidden>' + escapeHtml(a.text) + "</pre>"
      : "";

    return (
      '<article class="card">' +
        '<div class="card-head">' +
          '<div class="names"><span class="sym">$' + escapeHtml(a.symbol || "?") + "</span>" +
            '<span class="fullname">' + escapeHtml(a.name || "") + "</span></div>" +
          '<div class="when">' + escapeHtml(formatCst(a.created || a.created_ts)) + "</div>" +
        "</div>" +
        '<div class="pills">' + pills.join("") + "</div>" +
        (mintLinks.length ? '<div class="mint">' + mintLinks.join(" · ") + "</div>" : "") +
        (why ? '<p class="why"><strong>Why:</strong> ' + escapeHtml(why) + ".</p>" : "") +
        '<div class="grades">' +
          '<div class="grade-box"><h3>Wallet grade</h3>' +
            "<div>" + letterSpan(wallet.grade) + escapeHtml(scoreBit) +
            " <span class=\"addr\">" + escapeHtml(walletName) + "</span></div>" +
            (cobuyerBits ? '<p class="sub">Also bought: ' + cobuyerBits + "</p>" : "") +
            (wr ? '<p class="sub">' + escapeHtml(wr.replace(/^ · /, "")) + "</p>" : "") +
          "</div>" +
          '<div class="grade-box"><h3>Caller grade</h3>' +
            "<div>" + (caller.checked ? letterSpan(caller.grade || "–") : '<span class="faint">n/a</span>') + "</div>" +
            callerBody +
          "</div>" +
        "</div>" +
        lateHtml + outHtml + narrHtml + storyBlock +
      "</article>"
    );
  }

  function emptyState(data) {
    var sampleHint = useSample
      ? ""
      : ' To preview the layout with labeled example data, add <a href="?sample=1"><code>?sample=1</code></a> to this URL.';
    return (
      '<div class="empty">' +
        "<h2>No calls yet</h2>" +
        "<p>The public alert ledger is empty, so there is nothing to show. " +
        "Run <code>sma run</code> and then <code>python3 scripts/export_site_data.py</code> after the first real alert." +
        sampleHint + "</p>" +
      "</div>"
    );
  }

  function applyFilters(alerts) {
    var chain = $("filter-chain").value;
    var side = $("filter-side").value;
    return (alerts || []).filter(function (a) {
      if (chain !== "all" && String(a.chain || "").toLowerCase() !== chain) return false;
      if (side !== "all" && String(a.decision || "").toUpperCase() !== side) return false;
      return true;
    });
  }

  function render() {
    var data = state.data || { alerts: [], counts: {}, ledger: {}, example: false };
    var example = useSample || data.example;
    var banner = $("sample-banner");
    if (example) banner.removeAttribute("hidden");
    else banner.setAttribute("hidden", "");

    var err = $("status-error");
    if (state.error && !(data.alerts && data.alerts.length)) {
      err.textContent = state.error;
      err.removeAttribute("hidden");
    } else if (state.error) {
      err.textContent = state.error + " Showing the last loaded calls.";
      err.removeAttribute("hidden");
    } else {
      err.setAttribute("hidden", "");
    }

    var all = data.alerts || [];
    var shown = applyFilters(all);
    var feed = $("feed");
    if (!all.length) {
      feed.innerHTML = emptyState(data);
    } else if (!shown.length) {
      feed.innerHTML = '<div class="empty"><h2>No calls match these filters</h2>' +
        "<p>Try another chain or BUY/SELL filter. " + escapeHtml(String(all.length)) + " call(s) are in the ledger.</p></div>";
    } else {
      feed.innerHTML = shown.map(renderCard).join("");
    }

    var c = data.counts || {};
    var bits = [];
    bits.push((c.alerts || all.length) + " call" + ((c.alerts || all.length) === 1 ? "" : "s"));
    if (c.buy) bits.push(c.buy + " BUY");
    if (c.sell) bits.push(c.sell + " SELL");
    if (shown.length !== all.length) bits.push("showing " + shown.length);
    $("meta-counts").textContent = bits.join(" · ");
    var updated = formatUpdated(data.generated);
    var ago = state.loadedAt ? " · auto-refresh 60s" : "";
    $("meta-updated").textContent = (updated || "Waiting for data") + ago;

    var led = data.ledger || {};
    var ledgerLine = $("ledger-line");
    if (!led.exists) {
      ledgerLine.textContent = "Public ledger not published yet (public/ledger.jsonl). The page will fill in once alerts are exported.";
    } else {
      ledgerLine.textContent = "Ledger " + (led.path || "ledger.jsonl") + ": " + (led.lines || 0) +
        " line(s), chain " + (led.ok ? "OK" : "BROKEN") +
        (led.head ? ", head " + String(led.head).slice(0, 12) + "…" : "") + ".";
    }

    var w = (state.wallets && state.wallets.counts && state.wallets.counts.wallets) ||
      (state.wallets && state.wallets.wallets && state.wallets.wallets.length) || 0;
    var callers = state.callers;
    var nCallers = 0;
    if (callers && callers.counts) nCallers = callers.counts.callers || 0;
    else if (callers && callers.callers) nCallers = callers.callers.length;
    $("watch-wallets").textContent = w ? String(w) : "0";
    $("watch-callers").textContent = nCallers ? String(nCallers) : "0";
  }

  function fetchJson(url) {
    return fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error(url + " HTTP " + res.status);
        return res.json();
      });
  }

  function load() {
    var jobs = [
      fetchJson(alertsUrl).then(function (d) { state.data = d; state.error = null; }),
      fetchJson("data/callers.json").then(function (d) { state.callers = d; }).catch(function () {}),
      fetchJson("data/wallets.json").then(function (d) { state.wallets = d; }).catch(function () {})
    ];
    return Promise.all(jobs)
      .then(function () {
        state.loadedAt = new Date();
        render();
      })
      .catch(function (err) {
        state.error = useSample
          ? "Could not load example data (data/alerts.sample.json)."
          : "Could not load data/alerts.json. Serve the web/ folder over HTTP (python3 -m http.server -d web 8080).";
        if (!state.data) state.data = { alerts: [], counts: {}, ledger: { exists: false }, example: useSample };
        render();
        console.warn(err);
      });
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-toggle]");
    if (!btn) return;
    var el = document.getElementById(btn.getAttribute("data-toggle"));
    if (!el) return;
    var hide = !el.hasAttribute("hidden");
    if (hide) el.setAttribute("hidden", "");
    else el.removeAttribute("hidden");
    btn.textContent = hide ? "Show full description" : "Hide full description";
  });

  $("filter-chain").addEventListener("change", render);
  $("filter-side").addEventListener("change", render);

  load();
  timer = setInterval(load, REFRESH_MS);
})();
