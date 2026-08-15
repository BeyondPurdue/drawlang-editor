// experiments-demo-sync.js — status panel + manual reset button.
//
// Talks to /api/experiments/demo-sync/{status,reset-now}. Renders live
// previews of every source canvas by asking the server to render each
// one to SVG, so the page shows exactly what visitors will see after
// the next reset.

(function () {
  const $ = (id) => document.getElementById(id);

  function toast(msg, ms = 2400) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), ms);
  }

  function fmtDate(unixTs) {
    if (!unixTs) return "—";
    const d = new Date(unixTs * 1000);
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  }

  function fmtDuration(seconds) {
    if (!seconds || seconds < 0) return "—";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...opts });
    if (!res.ok) throw new Error(`${url} → ${res.status}`);
    return res.json();
  }

  function renderCanvasList(ulEl, canvases) {
    if (!canvases || canvases.length === 0) {
      ulEl.innerHTML = '<li class="empty">No canvases owned by this account yet.</li>';
      return;
    }
    ulEl.innerHTML = canvases.map((c) => `
      <li>
        <span class="name">
          ${escapeHtml(c.name || c.slug || "Untitled")}
          <span class="slug">${escapeHtml(c.slug || "")}</span>
        </span>
        <span class="count">${c.statement_count ?? 0} stmts</span>
      </li>
    `).join("");
  }

  async function renderPreview(container, canvas, sourceEmail) {
    // We hit the "as source" render by signing-request-forwarding —
    // since only the admin can see this page, and admin listing already
    // returns every canvas system-wide, /api/canvases/{slug}/render will
    // resolve by slug and admin owns the render. We just need the slug.
    try {
      const res = await fetch(
        `/api/canvases/${encodeURIComponent(canvas.slug)}/render`,
        { method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" }, body: "{}" },
      );
      if (!res.ok) throw new Error(`render → ${res.status}`);
      const j = await res.json();
      if (!j.ok) throw new Error(j.error || "render failed");
      container.innerHTML = `
        <div class="thumb-svg">${j.output}</div>
        <div class="thumb-label">
          <span class="name">${escapeHtml(canvas.name || canvas.slug)}</span>
          <span class="slug">${escapeHtml(canvas.slug)}</span>
        </div>
      `;
    } catch (err) {
      container.innerHTML = `
        <div class="thumb-err">preview failed: ${escapeHtml(String(err.message || err))}</div>
        <div class="thumb-label">
          <span class="name">${escapeHtml(canvas.name || canvas.slug)}</span>
          <span class="slug">${escapeHtml(canvas.slug)}</span>
        </div>
      `;
    }
  }

  async function refresh() {
    let s;
    try {
      s = await api("/api/experiments/demo-sync/status");
    } catch (err) {
      toast(`status: ${err.message || err}`);
      return;
    }

    // header text — replace placeholder emails with whatever the server
    // has configured (env override may swap it out).
    if (s.source && s.source.email) {
      $("src-email").textContent = s.source.email;
      $("src-email-2").textContent = s.source.email;
      $("src-who").textContent = s.source.email;
    }

    // last reset block
    const lr = s.last_reset || {};
    $("last-at").textContent = fmtDate(lr.at);
    const modeEl = $("last-mode");
    modeEl.className = "val mode-" + (lr.mode || "none");
    modeEl.textContent = lr.mode ? lr.mode.replace(/_/g, " ") : "never run this boot";
    if (lr.wiped) {
      $("last-wiped").textContent =
        `${lr.wiped.canvases}c · ${lr.wiped.frames}f · ${lr.wiped.library}l`;
    } else {
      $("last-wiped").textContent = "—";
    }
    if (lr.seeded && Object.keys(lr.seeded).length > 0) {
      const c = lr.seeded.canvases_copied ?? 0;
      const l = lr.seeded.library_copied ?? 0;
      $("last-seeded").textContent = `${c} canvases · ${l} library`;
    } else if (lr.mode === "fallback_seed") {
      $("last-seeded").textContent = "fallback seed";
    } else {
      $("last-seeded").textContent = "—";
    }
    $("next-in").textContent = fmtDuration(s.next_reset_seconds);

    // account panes
    renderCanvasList($("src-canvases"), s.source && s.source.canvases);
    renderCanvasList($("demo-canvases"), s.demo && s.demo.canvases);
    $("src-lib").textContent = `Library items owned by source: ${s.source?.n_library ?? 0}`;
    $("demo-lib").textContent = `Library items owned by demo: ${s.demo?.n_library ?? 0}`;

    // previews — render the source's canvases inline
    const previews = $("previews");
    const canvases = (s.source && s.source.canvases) || [];
    if (canvases.length === 0) {
      previews.innerHTML = '<div class="empty">Source account has no canvases yet. Sign in as the source account and create the showcase set, then click Reset now.</div>';
      return;
    }
    previews.innerHTML = canvases.map(() => '<div class="thumb"><div class="thumb-svg">…</div></div>').join("");
    const nodes = previews.querySelectorAll(".thumb");
    canvases.forEach((c, i) => {
      renderPreview(nodes[i], c, s.source.email);
    });
  }

  $("reset-btn").addEventListener("click", async () => {
    const btn = $("reset-btn");
    btn.disabled = true;
    btn.textContent = "Resetting…";
    try {
      const j = await api("/api/experiments/demo-sync/reset-now", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      if (j.ok) {
        toast(`reset ok · wiped ${j.canvases}c/${j.frames}f/${j.library}l · mode: ${j.seeded?.mode || "?"}`);
      } else {
        toast(`reset failed: ${j.reason || "unknown"}`);
      }
    } catch (err) {
      toast(`reset error: ${err.message || err}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Reset now";
      await refresh();
    }
  });

  refresh();
})();
