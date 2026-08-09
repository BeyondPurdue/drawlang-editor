/* Drawing Language Editor — v0.1 */

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

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

async function renderProgram({ silent = false } = {}) {
  const program = editor.value;

  if (!silent) setStatus("busy", "Rendering…");

  try {
    const r = await fetch("/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program, backend: "svg" }),
    });
    const data = await r.json();

    if (data.ok) {
      preview.innerHTML = data.output;
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
    fetch("/examples"),
    fetch("/drawings"),
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

function renderFilterTags() {
  // Preserve category order by first-seen occurrence
  const order = [];
  const seen = new Set();
  for (const e of allExamples) {
    const cat = e.category || "Examples";
    if (!seen.has(cat)) { seen.add(cat); order.push(cat); }
  }
  const cats = ["All", ...order];
  const wrap = $("filter-tags");
  wrap.innerHTML = "";
  for (const cat of cats) {
    const btn = document.createElement("button");
    btn.className = "tag" + (cat === activeCategory ? " active" : "");
    btn.type = "button";
    const count = cat === "All"
      ? allExamples.length
      : allExamples.filter(e => (e.category || "Examples") === cat).length;
    btn.innerHTML = `${escapeHtml(cat)}<span class="tag-count">${count}</span>`;
    btn.addEventListener("click", () => {
      activeCategory = cat;
      renderFilterTags();
      renderExampleList();
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

function loadExample(ex) {
  editor.value = ex.program;
  activeExample = ex.id;
  document.querySelectorAll(".example-list li").forEach(li => {
    li.classList.toggle("active", li.dataset.exampleId === ex.id);
  });
  renderProgram();
}

// ---------------------------------------------------------------------------
// Reference sidebar
// ---------------------------------------------------------------------------

async function loadReference() {
  const r = await fetch("/reference");
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
    const r = await fetch("/save", {
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
    const r = await fetch("/export/pdf", {
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

$("example-search").addEventListener("input", (e) => {
  searchQuery = e.target.value;
  renderExampleList();
});

// Init
loadReference();
loadExamples();
