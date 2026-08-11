// Shared top navigation for all editor pages.
// Every page includes <div id="app-nav"></div> right after <body> and this
// script renders a consistent nav bar with the current page highlighted.
(function () {
  const links = [
    { href: "/canvas-editor", label: "Canvas" },
    { href: "/library", label: "Library" },
    { href: "/frames-editor", label: "Frames" },
    { href: "/legacy", label: "Legacy v0.1" },
  ];
  const here = window.location.pathname.replace(/\/$/, "") || "/canvas-editor";
  const mount = document.getElementById("app-nav");
  if (!mount) return;
  const style = `
    #app-nav { display:flex; gap:0; align-items:center;
               background:#171614; color:#cdcccb;
               border-bottom:1px solid #2a2825;
               font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
               font-size:13px; }
    #app-nav .brand { padding:10px 16px; font-weight:600;
                      color:#f7f6f2; letter-spacing:.2px; }
    #app-nav .brand .mark { color:#01696f; margin-right:6px; }
    #app-nav .nav-link { padding:10px 14px; color:#a8a7a4;
                         text-decoration:none; border-bottom:2px solid transparent; }
    #app-nav .nav-link:hover { color:#f7f6f2; }
    #app-nav .nav-link.active { color:#f7f6f2;
                                border-bottom-color:#01696f; }
    #app-nav .spacer { flex:1; }
    #app-nav .health { padding:0 16px; color:#7a7974; font-size:12px; }
    #app-nav .health.ok { color:#4a7d3d; }
    #app-nav .health.err { color:#c25555; }
  `;
  const s = document.createElement("style");
  s.textContent = style;
  document.head.appendChild(s);
  const linksHtml = links.map((l) => {
    const active = here === l.href ? " active" : "";
    return `<a class="nav-link${active}" href="${l.href}">${l.label}</a>`;
  }).join("");
  mount.innerHTML = `
    <div class="brand"><span class="mark">◈</span>DrawLang</div>
    ${linksHtml}
    <div class="spacer"></div>
    <div class="health" id="app-nav-health">…</div>
  `;
  // Best-effort live health indicator.
  fetch("/health").then((r) => r.json()).then((d) => {
    const el = document.getElementById("app-nav-health");
    el.textContent = `v${d.spec_version} · ${d.git_sha || ""}`;
    el.className = "health ok";
  }).catch(() => {
    const el = document.getElementById("app-nav-health");
    if (el) { el.textContent = "offline"; el.className = "health err"; }
  });
})();
