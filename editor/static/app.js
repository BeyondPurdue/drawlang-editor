/* Drawing Language Editor — v0.1 */

// API base: works locally (relative /render) AND after deploy (proxy path).
// The sentinel is replaced with the actual proxy path at deploy time.
const API_BASE = (() => {
  const sentinel = "__PORT_8765__";
  // If sentinel was replaced, use it. Otherwise fall back to same-origin (dev).
  return sentinel.startsWith("__") ? "" : sentinel;
})();
const api = (path) => API_BASE + path;

const $ = (id) => document.getElementById(id);
const editor = $("editor");
const preview = $("preview");
const statusBar = $("status-bar");
const statusText = $("status-text");
const autorenderCb = $("autorender");

let renderTimer = null;
let activeExample = null;
let allExamples = [];      // full list from the server (examples + templates)
let activeCategory = "All";
let searchQuery = "";
let plansLoaded = false;   // true once /api/plans has been fetched
let plansCount = null;     // filled from HEAD or first fetch

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

async function renderProgram({ silent = false } = {}) {
  const program = editor.value;

  if (!silent) setStatus("busy", "Rendering…");

  try {
    const r = await fetch(api("/render"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program, backend: "svg" }),
    });
    const data = await r.json();

    if (data.ok) {
      preview.innerHTML = data.output;
      onPreviewSvgChanged();
      const stmtCount = countStatements(program);
      setStatus("ok", `OK · ${stmtCount} statement${stmtCount === 1 ? "" : "s"}`);
    } else {
      const idx = data.statement_index !== null && data.statement_index !== undefined
        ? ` (statement #${data.statement_index})`
        : "";
      setStatus("error", `${data.error_kind}${idx}: ${data.error}`);
    }
  } catch (err) {
    setStatus("error", `Network error: ${err.message}`);
  }
}

function setStatus(kind, text) {
  statusBar.className = "status-bar " + kind;
  statusText.textContent = text;
}

function countStatements(program) {
  return program.split(";").filter(s => s.trim().length > 0).length;
}

function scheduleAutoRender() {
  if (!autorenderCb.checked) return;
  clearTimeout(renderTimer);
  renderTimer = setTimeout(() => renderProgram({ silent: true }), 250);
}

// ---------------------------------------------------------------------------
// Examples + Templates (merged list with category tags)
// ---------------------------------------------------------------------------

async function loadExamples() {
  const [rEx, rDr] = await Promise.all([
    fetch(api("/examples")),
    fetch(api("/drawings")),
  ]);
  const examples = await rEx.json();
  const drawings = rDr.ok ? await rDr.json() : [];
  // "My drawings" first, then Examples, then imported templates
  allExamples = [...drawings, ...examples];

  renderFilterTags();
  renderExampleList();
  $("example-count").textContent = String(allExamples.length);

  // Auto-load the combined example on first visit for a satisfying first paint
  const combined = allExamples.find(e => e.id === "combined");
  if (combined) loadExample(combined);
}

async function loadPlansIfNeeded() {
  if (plansLoaded) return;
  plansLoaded = true;
  try {
    const r = await fetch(api("/api/plans"));
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const plans = await r.json();
    plansCount = plans.length;
    // Append plan-index entries to the merged list; renderers will pick them up.
    allExamples = allExamples.concat(plans);
    $("example-count").textContent = String(allExamples.length);
    renderFilterTags();
    renderExampleList();
  } catch (err) {
    plansLoaded = false; // allow retry
    console.error("loadPlansIfNeeded failed:", err);
  }
}

function renderFilterTags() {
  // Preserve category order by first-seen occurrence; always include Plans.
  const order = [];
  const seen = new Set();
  for (const e of allExamples) {
    const cat = e.category || "Examples";
    if (!seen.has(cat)) { seen.add(cat); order.push(cat); }
  }
  if (!seen.has("Plans")) { order.push("Plans"); seen.add("Plans"); }
  const cats = ["All", ...order];
  const wrap = $("filter-tags");
  wrap.innerHTML = "";
  for (const cat of cats) {
    const btn = document.createElement("button");
    btn.className = "tag" + (cat === activeCategory ? " active" : "");
    btn.type = "button";
    let count;
    if (cat === "All") {
      count = allExamples.length;
    } else if (cat === "Plans" && !plansLoaded) {
      count = "…";
    } else {
      count = allExamples.filter(e => (e.category || "Examples") === cat).length;
    }
    btn.innerHTML = `${escapeHtml(cat)}<span class="tag-count">${count}</span>`;
    btn.addEventListener("click", () => {
      activeCategory = cat;
      renderFilterTags();
      renderExampleList();
      if (cat === "Plans") loadPlansIfNeeded();
    });
    wrap.appendChild(btn);
  }
}

function renderExampleList() {
  const ul = $("example-list");
  ul.innerHTML = "";

  const q = searchQuery.trim().toLowerCase();
  const filtered = allExamples.filter(e => {
    const cat = e.category || "Examples";
    if (activeCategory !== "All" && cat !== activeCategory) return false;
    if (q && !e.title.toLowerCase().includes(q)) return false;
    return true;
  });

  // Cap what we render at once to keep the DOM light (1,468 pic_b entries
  // + 983 pic_ex is a lot). Show first N + a "load more" hint.
  const RENDER_CAP = 200;
  const shown = filtered.slice(0, RENDER_CAP);

  for (const ex of shown) {
    const li = document.createElement("li");
    li.dataset.exampleId = ex.id;
    if (activeExample === ex.id) li.classList.add("active");
    const cat = ex.category || "Examples";
    li.innerHTML =
      `<div class="example-title-row">` +
        `<span class="example-title">${escapeHtml(ex.title)}</span>` +
        `<span class="cat-badge cat-${slugify(cat)}">${escapeHtml(cat)}</span>` +
      `</div>` +
      `<span class="example-desc">${escapeHtml(ex.description || "")}</span>`;
    li.addEventListener("click", () => loadExample(ex));
    ul.appendChild(li);
  }

  if (filtered.length > RENDER_CAP) {
    const more = document.createElement("li");
    more.className = "more-hint";
    more.textContent = `Showing ${RENDER_CAP} of ${filtered.length}. Refine the filter to see more.`;
    ul.appendChild(more);
  } else if (filtered.length === 0) {
    const empty = document.createElement("li");
    empty.className = "more-hint";
    empty.textContent = "No matches. Clear the filter or search.";
    ul.appendChild(empty);
  }
}

function slugify(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

async function loadExample(ex) {
  activeExample = ex.id;
  document.querySelectorAll(".example-list li").forEach(li => {
    li.classList.toggle("active", li.dataset.exampleId === ex.id);
  });
  if (ex.lazy && ex.plan_id != null) {
    // Composed plan program — fetch on demand.
    editor.value = `# Loading plan ${ex.plan_id} page ${ex.page}…\n`;
    renderProgram({ silent: true });
    try {
      const r = await fetch(api(`/api/plans/${ex.plan_id}?page=${ex.page}`));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      editor.value = data.program;
      // Cache on the entry so we do not refetch on re-click.
      ex.program = data.program;
      ex.lazy = false;
    } catch (err) {
      editor.value =
        `# Failed to load plan ${ex.plan_id} page ${ex.page}: ${err.message}\n`;
    }
    renderProgram();
    return;
  }
  editor.value = ex.program;
  renderProgram();
}

// ---------------------------------------------------------------------------
// Reference sidebar
// ---------------------------------------------------------------------------

async function loadReference() {
  const r = await fetch(api("/reference"));
  const ref = await r.json();
  $("spec-version").textContent = ref.spec_version;

  renderRefList("ref-core", ref.core_opcodes, "signature", "desc");
  renderRefList("ref-ext",  ref.extension_opcodes, "signature", "desc");
  renderRefList("ref-mods", ref.modifiers, "mod", "desc");

  $("ref-footer").innerHTML =
    `<strong>Coordinates:</strong> ${escapeHtml(ref.coord_system)}<br>` +
    `<strong>Pen:</strong> ${escapeHtml(ref.pen_state)}`;
}

function renderRefList(elId, items, sigKey, descKey) {
  const ul = $(elId);
  ul.innerHTML = "";
  for (const it of items) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="ref-sig">${escapeHtml(it[sigKey])}</span><span class="ref-desc">${escapeHtml(it[descKey])}</span>`;
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Save (persist edited template as user drawing)
// ---------------------------------------------------------------------------

async function saveDrawing() {
  const defaultName = activeExample ? `${activeExample}-edit` : "drawing";
  const name = prompt("Save this drawing as:", defaultName);
  if (!name) return;
  setStatus("busy", "Saving…");
  try {
    const r = await fetch(api("/save"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        program: editor.value,
        source_id: activeExample || null,
      }),
    });
    const data = await r.json();
    if (data.ok) {
      setStatus("ok", `Saved as ${data.slug}`);
      await loadExamples();  // refresh so "My drawings" shows the new entry
    } else {
      setStatus("error", `Save failed: ${data.error || "unknown"}`);
    }
  } catch (err) {
    setStatus("error", `Save error: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

function exportSVG() {
  const svgEl = preview.querySelector("svg");
  if (!svgEl) { setStatus("error", "Nothing to export — render first."); return; }
  const svgText = svgEl.outerHTML;
  downloadBlob(new Blob([svgText], { type: "image/svg+xml" }), "drawing.svg");
}

async function exportPDF() {
  setStatus("busy", "Generating PDF…");
  try {
    const r = await fetch(api("/export/pdf"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program: editor.value, backend: "ps" }),
    });
    if (!r.ok) {
      const t = await r.text();
      setStatus("error", `PDF export failed: ${t}`);
      return;
    }
    const blob = await r.blob();
    downloadBlob(blob, "drawing.pdf");
    setStatus("ok", "PDF exported.");
  } catch (err) {
    setStatus("error", `PDF export error: ${err.message}`);
  }
}

async function exportDXF() {
  setStatus("busy", "Generating DXF…");
  try {
    const r = await fetch(api("/export/dxf"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program: editor.value }),
    });
    if (!r.ok) {
      const t = await r.text();
      setStatus("error", `DXF export failed: ${t}`);
      return;
    }
    downloadBlob(await r.blob(), "drawing.dxf");
    setStatus("ok", "DXF exported.");
  } catch (err) {
    setStatus("error", `DXF export error: ${err.message}`);
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// ---------------------------------------------------------------------------
// Wire up events
// ---------------------------------------------------------------------------

editor.addEventListener("input", scheduleAutoRender);

editor.addEventListener("keydown", (e) => {
  // Ctrl/Cmd+Enter renders
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    renderProgram();
  }
});

$("render-btn").addEventListener("click", () => renderProgram());
$("save-btn").addEventListener("click", saveDrawing);
$("export-svg").addEventListener("click", exportSVG);
$("export-pdf").addEventListener("click", exportPDF);
const _dxfBtnLegacy = document.getElementById("export-dxf");
if (_dxfBtnLegacy) _dxfBtnLegacy.addEventListener("click", exportDXF);

// v0.7: Export DrawLang — dump the current editor text as a .drawlang file
// so the user can save/load their scratch work without going through the
// canvas save flow.
$("export-dl").addEventListener("click", () => {
  const program = editor.value || "";
  const blob = new Blob([program], {type: "text/plain;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "editor.drawlang"; a.click();
  URL.revokeObjectURL(url);
});

$("example-search").addEventListener("input", (e) => {
  searchQuery = e.target.value;
  renderExampleList();
});

// ---------------------------------------------------------------------------
// Preview pan + zoom (native 1:1 by default, legacy-style)
//   scale  = CSS transform scale factor (1.0 = 1 unit ↔ 1 CSS px)
//   tx, ty = translation in CSS px (top-left corner offset)
//   Content coord (cx, cy) maps to screen (cx*scale + tx, cy*scale + ty).
//   To zoom around a screen point (sx, sy) at new scale s2:
//     tx' = sx - (sx - tx) * s2/scale
//     ty' = sy - (sy - ty) * s2/scale
// ---------------------------------------------------------------------------

const view = { scale: 1, tx: 0, ty: 0 };
const MIN_SCALE = 0.02;
const MAX_SCALE = 8;
const zoomLevel = $("zoom-level");

function currentSvg() { return preview.querySelector("svg"); }

function contentSize(svg) {
  const w = parseFloat(svg.getAttribute("data-content-width") || svg.getAttribute("width") || 0);
  const h = parseFloat(svg.getAttribute("data-content-height") || svg.getAttribute("height") || 0);
  return { w, h };
}

function applyView() {
  const svg = currentSvg();
  if (!svg) return;
  svg.style.transform = `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`;
  zoomLevel.textContent = Math.round(view.scale * 100) + "%";
}

function setZoomAround(newScale, sx, sy) {
  newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
  // Origin-relative screen point (sx, sy is relative to preview canvas top-left)
  view.tx = sx - (sx - view.tx) * (newScale / view.scale);
  view.ty = sy - (sy - view.ty) * (newScale / view.scale);
  view.scale = newScale;
  applyView();
}

function fitToContainer() {
  const svg = currentSvg();
  if (!svg) return;
  const { w, h } = contentSize(svg);
  if (!w || !h) return;
  const cw = preview.clientWidth, ch = preview.clientHeight;
  const pad = 24;
  const s = Math.min((cw - pad) / w, (ch - pad) / h, 1);
  view.scale = Math.max(MIN_SCALE, s);
  view.tx = (cw - w * view.scale) / 2;
  view.ty = (ch - h * view.scale) / 2;
  applyView();
}

function resetOneToOne() {
  const svg = currentSvg();
  if (!svg) return;
  const { w, h } = contentSize(svg);
  const cw = preview.clientWidth, ch = preview.clientHeight;
  view.scale = 1;
  // Center if it fits, otherwise anchor top-left with a small margin
  view.tx = w <= cw ? (cw - w) / 2 : 12;
  view.ty = h <= ch ? (ch - h) / 2 : 12;
  applyView();
}

// Called whenever preview.innerHTML has been replaced with a new SVG.
// - Small drawing (fits): show at native 1:1, centered.
// - Large drawing (bigger than pane): fit-to-container so the whole sheet
//   is visible. This works because the SVG uses non-scaling-stroke, so
//   1-px lines stay 1 CSS px wide even at 2% zoom — the drawing stays
//   legible instead of collapsing to a black smudge.
// User can always click 1:1 or use Ctrl+wheel to zoom in.
function onPreviewSvgChanged() {
  // v0.6: the SVG now fills the preview pane natively via CSS + its own
  // preserveAspectRatio. Start with an identity CSS transform so the sheet
  // sits at 100% fit; the user can wheel-zoom / drag-pan from there.
  const svg = currentSvg();
  if (!svg) return;
  view.scale = 1;
  view.tx = 0;
  view.ty = 0;
  applyView();
}

// --- Pan (mouse drag) ---
let dragging = null;
preview.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  if (!currentSvg()) return;
  dragging = { sx: e.clientX, sy: e.clientY, tx0: view.tx, ty0: view.ty };
  preview.classList.add("dragging");
  e.preventDefault();
});
window.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  view.tx = dragging.tx0 + (e.clientX - dragging.sx);
  view.ty = dragging.ty0 + (e.clientY - dragging.sy);
  applyView();
});
window.addEventListener("mouseup", () => {
  if (!dragging) return;
  dragging = null;
  preview.classList.remove("dragging");
});

// --- Zoom (Ctrl+wheel, plain wheel scrolls to zoom in/out too, matching CAD apps) ---
preview.addEventListener("wheel", (e) => {
  if (!currentSvg()) return;
  if (!e.ctrlKey && !e.metaKey) return; // require modifier so page scroll still works
  e.preventDefault();
  const rect = preview.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  setZoomAround(view.scale * factor, sx, sy);
}, { passive: false });

// --- Buttons ---
function centerZoom(factor) {
  const rect = preview.getBoundingClientRect();
  setZoomAround(view.scale * factor, rect.width / 2, rect.height / 2);
}
$("zoom-in").addEventListener("click", () => centerZoom(1.25));
$("zoom-out").addEventListener("click", () => centerZoom(1 / 1.25));
$("zoom-one").addEventListener("click", resetOneToOne);
$("zoom-fit").addEventListener("click", fitToContainer);

// Init
loadReference();
loadExamples();
