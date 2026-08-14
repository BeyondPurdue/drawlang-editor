// admin-stats.js — load and render the /admin/stats dashboard.
// No framework. Straight fetch + DOM.

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error(url + " → " + r.status);
    return r.json();
  }

  function fmt(n) {
    if (n == null) return "–";
    return Number(n).toLocaleString("en-US");
  }

  function fmtTs(iso) {
    // Show local time, seconds precision.
    try {
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    } catch (_) { return iso; }
  }

  function statusClass(s) {
    if (s >= 500) return "status-5xx";
    if (s >= 400) return "status-4xx";
    if (s >= 300) return "status-3xx";
    return "status-2xx";
  }

  // ---- KPIs -----------------------------------------------------------
  async function loadKpis() {
    const s = await getJSON("/api/admin/stats/summary");
    $("k-total-views").textContent    = fmt(s.total_views);
    $("k-total-sessions").textContent = fmt(s.total_sessions);
    $("k-views-24h").textContent      = fmt(s.views_24h);
    $("k-sessions-24h").textContent   = fmt(s.sessions_24h);
    $("k-views-7d").textContent       = fmt(s.views_7d);
    $("k-sessions-7d").textContent    = fmt(s.sessions_7d);
  }

  // ---- Chart (SVG bars) ----------------------------------------------
  function renderChart(rows) {
    const svg = $("chart");
    svg.innerHTML = "";
    if (!rows.length) {
      svg.innerHTML = '<text x="400" y="100" text-anchor="middle" fill="#7a7974" font-size="12">No data yet</text>';
      return;
    }
    const W = 800, H = 200, PAD_L = 32, PAD_R = 8, PAD_T = 8, PAD_B = 28;
    const plotW = W - PAD_L - PAD_R;
    const plotH = H - PAD_T - PAD_B;
    const maxViews = Math.max(1, ...rows.map(r => r.views));
    const n = rows.length;
    const bw = plotW / n;
    let bars = "";
    rows.forEach((r, i) => {
      const x = PAD_L + i * bw;
      const hV = (r.views    / maxViews) * plotH;
      const hS = (r.sessions / maxViews) * plotH;
      const yV = PAD_T + plotH - hV;
      const yS = PAD_T + plotH - hS;
      const w = Math.max(1, bw - 2);
      // sessions behind, views in front
      bars += `<rect class="bar-sess" x="${x+1}" y="${yS}" width="${w}" height="${hS}"><title>${r.day}: ${r.sessions} visitors</title></rect>`;
      bars += `<rect class="bar"      x="${x+1+w*0.15}" y="${yV}" width="${w*0.7}" height="${hV}"><title>${r.day}: ${r.views} views</title></rect>`;
    });

    // y-axis: 3 ticks
    const ticks = [];
    for (let t = 0; t <= 3; t++) {
      const v = Math.round((maxViews * t) / 3);
      const y = PAD_T + plotH - (v / maxViews) * plotH;
      ticks.push(`<line x1="${PAD_L}" x2="${W-PAD_R}" y1="${y}" y2="${y}" stroke="#e7e5df"/>`);
      ticks.push(`<text x="${PAD_L-4}" y="${y+3}" text-anchor="end" font-size="10" fill="#7a7974">${v}</text>`);
    }
    // x-axis labels — first, middle, last
    const idxs = n === 1 ? [0] : n === 2 ? [0, n-1] : [0, Math.floor(n/2), n-1];
    let xlabels = "";
    idxs.forEach(i => {
      const x = PAD_L + i * bw + bw/2;
      xlabels += `<text x="${x}" y="${H-8}" text-anchor="middle" font-size="10" fill="#7a7974">${rows[i].day.slice(5)}</text>`;
    });

    svg.innerHTML = `<g class="axis">${ticks.join("")}${xlabels}</g><g>${bars}</g>`;
  }

  async function loadChart() {
    const days = $("days-sel").value;
    const j = await getJSON("/api/admin/stats/by-day?days=" + days);
    renderChart(j.days || []);
  }

  // ---- Tables ---------------------------------------------------------
  function tableFrom(rows, cols, empty) {
    if (!rows.length) return `<div class="empty">${empty}</div>`;
    const head = cols.map(c => `<th class="${c.num ? 'num' : ''}">${c.label}</th>`).join("");
    const body = rows.map(r =>
      "<tr>" + cols.map(c => {
        const v = c.cell(r);
        const cls = [c.num ? "num" : "", c.mono ? "mono" : "", c.extra ? c.extra(r) : ""]
          .filter(Boolean).join(" ");
        return `<td class="${cls}">${v}</td>`;
      }).join("") + "</tr>"
    ).join("");
    return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c])
    );
  }

  async function loadTopPages() {
    const j = await getJSON("/api/admin/stats/top-pages?limit=20");
    const rows = j.pages || [];
    $("top-pages").innerHTML = tableFrom(rows, [
      { label: "Page",     cell: r => `<span class="path">${escapeHtml(r.path)}</span>`, mono: true },
      { label: "Views",    cell: r => fmt(r.views),    num: true },
      { label: "Visitors", cell: r => fmt(r.sessions), num: true },
    ], "No page views yet.");

    if (rows.length) {
      $("k-top-page").textContent = rows[0].path;
      $("k-top-page-count").textContent = fmt(rows[0].views) + " views";
    }
  }

  async function loadReferrers() {
    const j = await getJSON("/api/admin/stats/referrers?limit=20");
    const rows = j.referrers || [];
    $("referrers").innerHTML = tableFrom(rows, [
      { label: "Referrer", cell: r => escapeHtml(r.host), mono: true },
      { label: "Views",    cell: r => fmt(r.views),    num: true },
      { label: "Visitors", cell: r => fmt(r.sessions), num: true },
    ], "No referrers logged yet.");

    if (rows.length) {
      $("k-top-ref").textContent = rows[0].host;
      $("k-top-ref-count").textContent = fmt(rows[0].views) + " views";
    }
  }

  function flag(cc) {
    if (!cc || cc === "??") return '<span class="flag">🌐</span>';
    // ISO country code → flag emoji.
    const base = 0x1F1E6;
    const c1 = cc.charCodeAt(0) - 65 + base;
    const c2 = cc.charCodeAt(1) - 65 + base;
    return `<span class="flag">${String.fromCodePoint(c1, c2)}</span>`;
  }

  async function loadCountries() {
    const j = await getJSON("/api/admin/stats/countries?limit=30");
    const rows = j.countries || [];
    $("countries").innerHTML = tableFrom(rows, [
      { label: "Country",  cell: r => flag(r.country) + escapeHtml(r.country) },
      { label: "Views",    cell: r => fmt(r.views),    num: true },
      { label: "Visitors", cell: r => fmt(r.sessions), num: true },
    ], "No country data yet.");
  }

  async function loadRecent() {
    const j = await getJSON("/api/admin/stats/recent?limit=100");
    const rows = j.visits || [];
    $("recent").innerHTML = tableFrom(rows, [
      { label: "When",     cell: r => fmtTs(r.ts) },
      { label: "Page",     cell: r => `<span class="path">${escapeHtml(r.path)}</span>`, mono: true },
      { label: "Status",   cell: r => `<span class="${statusClass(r.status)}">${r.status}</span>`, num: true },
      { label: "User",     cell: r => escapeHtml(r.user_email || "—") },
      { label: "Country",  cell: r => escapeHtml(r.country || "—") },
      { label: "IP block", cell: r => escapeHtml(r.ip_prefix || "—"), mono: true },
      { label: "Referrer", cell: r => escapeHtml(r.referrer || "—"), mono: true },
    ], "No visits recorded yet.");
  }

  // ---- Boot -----------------------------------------------------------
  async function refresh() {
    try {
      await Promise.all([
        loadKpis(),
        loadChart(),
        loadTopPages(),
        loadReferrers(),
        loadCountries(),
        loadRecent(),
      ]);
    } catch (e) {
      console.error("stats refresh failed", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Show current admin in the header.
    fetch("/api/auth/me", { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null)
      .then(j => {
        if (j && j.user) {
          $("who").textContent = (j.user.display_name || j.user.email) + " (admin)";
        }
      });

    $("days-sel").addEventListener("change", loadChart);
    refresh();
    // Auto-refresh every 60s.
    setInterval(refresh, 60_000);
  });
})();
