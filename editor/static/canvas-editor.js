// Canvas editor — talks to /api/canvases and /api/library

const $ = (id) => document.getElementById(id);

const state = {
  canvases: [],
  currentCanvas: null,       // slug
  statements: [],
  selectedIds: new Set(),    // for multi-select
  library: [],
  primitives: [],
  opcodes: [],
  activeTab: "primitives",   // sidebar tab: 'primitives' | 'symbols'
  // pendingDrop: null | {kind: 'symbol', slug} | {kind: 'primitive', id, values}
  pendingDrop: null,
  svg: null,
  vbox: null,                // viewBox as [x,y,w,h]
};

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(`${res.status}: ${t}`);
  }
  return res.json();
}

// --------------------------------------------------------------------------
// Canvas list + selector
// --------------------------------------------------------------------------
async function refreshCanvasList() {
  const { canvases } = await api("/api/canvases");
  state.canvases = canvases;
  const sel = $("canvas-select");
  const cur = state.currentCanvas;
  sel.innerHTML = '<option value="">— choose canvas —</option>' +
    canvases.map((c) =>
      `<option value="${c.slug}"${c.slug === cur ? " selected" : ""}>${c.name} (${c.statement_count})</option>`
    ).join("");
}

async function loadCanvas(slug) {
  if (!slug) {
    state.currentCanvas = null;
    state.statements = [];
    $("svg-host").innerHTML = "";
    renderStatementList();
    return;
  }
  const data = await api(`/api/canvases/${slug}`);
  state.currentCanvas = slug;
  state.statements = data.statements;
  state.selectedIds = new Set();
  const frameSel = $("frame-select");
  if (frameSel) frameSel.value = data.canvas?.frame_id || "";
  const renameEl = $("canvas-rename");
  if (renameEl) renameEl.value = data.canvas?.name || "";
  renderStatementList();
  await renderCanvas();
}

async function loadFrameList() {
  try {
    const res = await fetch("/api/frames");
    if (!res.ok) return;
    const data = await res.json();
    const frames = data.frames || data;
    const sel = $("frame-select");
    if (!sel) return;
    // Preserve the placeholder option
    sel.innerHTML = '<option value="">— none —</option>';
    for (const f of frames) {
      const opt = document.createElement("option");
      opt.value = f.id || f.slug;
      opt.textContent = f.name || f.id || f.slug;
      sel.appendChild(opt);
    }
  } catch (e) {
    console.error("frame list failed", e);
  }
}

async function renderCanvas() {
  if (!state.currentCanvas) return;
  // v0.7: request tagged render so each canvas statement's SVG is
  // wrapped in <g data-statement-id="N">…</g>. This is what makes
  // canvas ↔ statements bidirectional selection work.
  const res = await api(`/api/canvases/${state.currentCanvas}/render?tagged=true`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  $("svg-host").innerHTML = res.output;
  const svg = $("svg-host").querySelector("svg");
  state.svg = svg;
  state.svgSource = res.output || "";
  if (svg) {
    // parse viewBox
    const vb = svg.getAttribute("viewBox");
    if (vb) state.vbox = vb.split(/\s+/).map(Number);
    // constrain size
    svg.style.maxWidth = "100%";
    svg.style.height = "auto";
    hookSvgEvents(svg);
  }
  $("stmt-status").textContent = `Rendered ${state.statements.length} statements`;
  $("stmt-status").className = "status ok";
  // Re-apply any pre-existing selection to the newly rendered SVG.
  applySelectionHighlights();
}

function hookSvgEvents(svg) {
  // DrawLang paper coords are y-down; the renderer flips the world with
  // transform="scale(1 -1)" so PDF/print orientation matches. Undo that flip
  // when converting screen -> DrawLang coordinates.
  const toPaper = (p) => ({ x: p.x, y: -p.y });
  svg.addEventListener("mousemove", (e) => {
    const p = toPaper(svgPoint(svg, e));
    $("coord-hud").textContent = `x: ${Math.round(p.x)}  y: ${Math.round(p.y)}`;
  });
  // Attach to the host container so clicks always land, even on inner <g>
  // elements where getScreenCTM() can be null.
  const host = $("svg-host");
  host.onclick = (e) => {
    if (state.pendingDrop) {
      const p = toPaper(svgPoint(svg, e));
      const drop = state.pendingDrop;
      state.pendingDrop = null;
      svg.style.cursor = "crosshair";
      if (drop.kind === "opcode") {
        dropOpcodeHere(drop.opcode, drop.args, p.x, p.y);
      } else if (drop.kind === "primitive") {
        dropPrimitiveHere(drop.id, drop.values, p.x, p.y);
      } else {
        const slug = typeof drop === "string" ? drop : drop.slug;
        dropLibraryHere(slug, p.x, p.y);
      }
      return;
    }
    // v0.7: no pending drop → treat as a selection click. Walk up the
    // DOM from the actual target to find the nearest ancestor tagged
    // with data-statement-id. If none, clear selection.
    const wrapper = e.target.closest("[data-statement-id]");
    if (wrapper) {
      const id = parseInt(wrapper.getAttribute("data-statement-id"), 10);
      if (Number.isFinite(id)) selectStatementById(id, e.shiftKey);
    } else {
      selectStatementById(null, false);
    }
  };
}

// v0.7 selection helpers — single source of truth = state.selectedIds.
// The statements list, canvas SVG, and Edit Selected panel all read from
// this set. Any mutation must call `applySelectionHighlights()`.
function selectStatementById(id, additive) {
  if (id === null || id === undefined) {
    state.selectedIds.clear();
  } else if (additive) {
    if (state.selectedIds.has(id)) state.selectedIds.delete(id);
    else state.selectedIds.add(id);
  } else {
    state.selectedIds.clear();
    state.selectedIds.add(id);
  }
  applySelectionHighlights();
  showEditPanel();
}

function applySelectionHighlights() {
  // Statements list rows use data-id on .stmt-row
  document.querySelectorAll("#stmt-list .stmt-row").forEach((el) => {
    const rid = parseInt(el.dataset.id, 10);
    el.classList.toggle("selected", state.selectedIds.has(rid));
  });
  // Canvas SVG wrappers
  if (state.svg) {
    state.svg.querySelectorAll("[data-statement-id]").forEach((el) => {
      const rid = parseInt(el.getAttribute("data-statement-id"), 10);
      const sel = state.selectedIds.has(rid);
      // Halo: bump stroke-width and add a colored outline via CSS filter.
      // Cheap and works without a second render pass.
      if (sel) {
        el.setAttribute("data-selected", "true");
      } else {
        el.removeAttribute("data-selected");
      }
    });
  }
}

function svgPoint(svg, evt) {
  // Try native SVG matrix first.
  try {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (ctm) {
      const inv = ctm.inverse();
      const p = pt.matrixTransform(inv);
      if (isFinite(p.x) && isFinite(p.y)) return p;
    }
  } catch (_) { /* fall through */ }
  // Fallback: manual viewBox math from bounding rect.
  const rect = svg.getBoundingClientRect();
  const vb = (svg.getAttribute("viewBox") || "0 0 1 1").split(/\s+/).map(Number);
  const [vx, vy, vw, vh] = vb;
  const x = vx + ((evt.clientX - rect.left) / rect.width) * vw;
  const y = vy + ((evt.clientY - rect.top) / rect.height) * vh;
  return { x, y };
}

// --------------------------------------------------------------------------
// Statement list + editing
// --------------------------------------------------------------------------
function renderStatementList() {
  const el = $("stmt-list");
  if (!state.statements.length) {
    el.innerHTML = '<div style="color:#7a7974">No statements yet. Add one below.</div>';
    return;
  }
  el.innerHTML = state.statements.map((s) => {
    const sel = state.selectedIds.has(s.id) ? " selected" : "";
    return `<div class="stmt-row${sel}" data-id="${s.id}">
      <span class="stmt-seq">${s.seq}</span>
      <span class="stmt-op" data-edit-op="${s.id}" title="Double-click to edit opcode">${escapeAttr(s.opcode)}</span>
      <span class="stmt-args" data-edit-args="${s.id}" title="Double-click to edit args">${escapeAttr(s.args)}</span>
      <span class="stmt-del" data-del="${s.id}" title="Delete">✕</span>
    </div>`;
  }).join("");

  el.querySelectorAll(".stmt-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      // Don't hijack clicks on the delete X or on an active inline editor.
      if (e.target.dataset.del) return;
      if (e.target.tagName === "INPUT") return;
      const id = parseInt(row.dataset.id);
      // v0.7: route through the shared selection helper so the canvas SVG,
      // statements list, and Edit Selected panel stay in sync.
      selectStatementById(id, e.shiftKey);
    });
  });
  // v0.7: inline edit — double-click the opcode or args cell to type a new
  // value. Enter commits, Escape cancels. Uses the same PATCH endpoint the
  // Edit Selected form uses so validation stays in one place.
  el.querySelectorAll("[data-edit-op],[data-edit-args]").forEach((cell) => {
    cell.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      startInlineEdit(cell);
    });
  });
  el.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.del);
      await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
        method: "DELETE",
      });
      await reloadStatements();
    });
  });
}

function startInlineEdit(cell) {
  const id = parseInt(cell.dataset.editOp || cell.dataset.editArgs);
  const field = cell.dataset.editOp ? "opcode" : "args";
  const stmt = state.statements.find((s) => s.id === id);
  if (!stmt) return;
  const original = stmt[field];
  const input = document.createElement("input");
  input.type = "text";
  input.value = original;
  input.className = "stmt-inline-edit";
  input.style.width = field === "opcode" ? "3em" : "100%";
  cell.replaceChildren(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newVal = input.value.trim();
    if (newVal === original) {
      renderStatementList();
      return;
    }
    try {
      await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ [field]: newVal }),
      });
      await reloadStatements();
    } catch (err) {
      alert(`edit failed: ${err.message}`);
      renderStatementList();
    }
  };
  const cancel = () => renderStatementList();
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    else if (e.key === "Escape") { input.removeEventListener("blur", commit); cancel(); }
  });
}

// --------------------------------------------------------------------------
// Selection transforms — computed purely on the args of existing opcodes.
// v0.6 drawlang stays LOCKED; nothing here introduces new opcodes.
// --------------------------------------------------------------------------

// Reload the current canvas's statements + re-render. Idempotent; safe to
// call after any mutation (PATCH / DELETE / POST /statements).
async function reloadStatements() {
  if (!state.currentCanvas) return;
  await loadCanvas(state.currentCanvas);
}

// Parse a statement's args string into an array of numbers where possible.
// Falls back to strings (e.g. tx text argument).
function _parseArgs(s) {
  return s.split(",").map((p) => {
    const t = p.trim();
    const n = Number(t);
    return Number.isFinite(n) && t !== "" ? n : t;
  });
}
function _joinArgs(arr) {
  // + 0 normalises -0 -> 0 so we don't emit "-0" back into drawlang.
  return arr.map((v) => (typeof v === "number" ? String(v + 0) : v)).join(",");
}

// Return {cx, cy} — the average of the ma/mr chain endpoints in the selection.
// Simple heuristic: use the last known absolute position of ma/rt/ci opcodes;
// for a mixed selection fall back to (0,0). This is only used as the pivot
// for rotate-around-selection when a real absolute anchor cannot be found.
function _selectionCentroid(stmts) {
  const xs = [], ys = [];
  for (const s of stmts) {
    const a = _parseArgs(s.args);
    if ((s.opcode === "ma" || s.opcode === "rt" || s.opcode === "ci") &&
        typeof a[0] === "number" && typeof a[1] === "number") {
      xs.push(a[0]); ys.push(a[1]);
    }
  }
  if (!xs.length) return { cx: 0, cy: 0 };
  const cx = xs.reduce((s, v) => s + v, 0) / xs.length;
  const cy = ys.reduce((s, v) => s + v, 0) / ys.length;
  return { cx, cy };
}

// Apply a per-statement transform and PATCH each changed row.
// `fn(stmt) => new args string` (return null to skip a statement).
async function _transformSelection(fn) {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  const changed = [];
  for (const id of ids) {
    const stmt = state.statements.find((s) => s.id === id);
    if (!stmt) continue;
    const newArgs = fn(stmt);
    if (newArgs === null || newArgs === stmt.args) continue;
    changed.push({ id, args: newArgs });
  }
  for (const c of changed) {
    await api(`/api/canvases/${state.currentCanvas}/statements/${c.id}`, {
      method: "PATCH",
      body: JSON.stringify({ args: c.args }),
    });
  }
  await reloadStatements();
}

// Rotation: quadrant only (90 CW / 90 CCW / 180). Pivot is the selection
// centroid; relative opcodes (mr, dl) rotate around origin (they're deltas).
function _rotateArgs(stmt, quadrant, pivot) {
  const a = _parseArgs(stmt.args);
  const op = stmt.opcode;
  // helpers
  const rot = (x, y) => {
    if (quadrant === 90)  return [-y,  x]; // CCW
    if (quadrant === -90) return [ y, -x]; // CW
    return [-x, -y];                        // 180
  };
  if (op === "mr" || op === "dl") {
    if (typeof a[0] === "number" && typeof a[1] === "number") {
      const [nx, ny] = rot(a[0], a[1]);
      return _joinArgs([nx, ny, ...a.slice(2)]);
    }
  } else if (op === "ma") {
    if (typeof a[0] === "number" && typeof a[1] === "number") {
      const [nx, ny] = rot(a[0] - pivot.cx, a[1] - pivot.cy);
      return _joinArgs([Math.round(nx + pivot.cx), Math.round(ny + pivot.cy), ...a.slice(2)]);
    }
  } else if (op === "rt") {
    // rt w,h — 90° rotation swaps w<->h; 180° keeps them
    if (Math.abs(quadrant) === 90 && typeof a[0] === "number" && typeof a[1] === "number") {
      return _joinArgs([a[1], a[0], ...a.slice(2)]);
    }
  }
  // ci (radius unchanged), tx (glyph rotation not in v0.6), everything else: skip
  return null;
}

// Mirror axis: "h" flips X (left↔right), "v" flips Y (top↔bottom).
function _mirrorArgs(stmt, axis, pivot) {
  const a = _parseArgs(stmt.args);
  const op = stmt.opcode;
  if (op === "mr" || op === "dl") {
    if (typeof a[0] !== "number" || typeof a[1] !== "number") return null;
    return axis === "h"
      ? _joinArgs([-a[0], a[1], ...a.slice(2)])
      : _joinArgs([a[0], -a[1], ...a.slice(2)]);
  }
  if (op === "ma") {
    if (typeof a[0] !== "number" || typeof a[1] !== "number") return null;
    return axis === "h"
      ? _joinArgs([Math.round(2 * pivot.cx - a[0]), a[1], ...a.slice(2)])
      : _joinArgs([a[0], Math.round(2 * pivot.cy - a[1]), ...a.slice(2)]);
  }
  // rt/ci width/radius unchanged, tx unchanged
  return null;
}

async function rotateSelection(quadrant) {
  const stmts = state.statements.filter((s) => state.selectedIds.has(s.id));
  const pivot = _selectionCentroid(stmts);
  await _transformSelection((s) => _rotateArgs(s, quadrant, pivot));
}
async function mirrorSelection(axis) {
  const stmts = state.statements.filter((s) => state.selectedIds.has(s.id));
  const pivot = _selectionCentroid(stmts);
  await _transformSelection((s) => _mirrorArgs(s, axis, pivot));
}

async function duplicateSelection() {
  const ids = [...state.selectedIds];
  const stmts = state.statements
    .filter((s) => ids.includes(s.id))
    .sort((a, b) => a.seq - b.seq);
  if (!stmts.length) return;
  // Append copies via the /statements program endpoint — one round-trip.
  const program = stmts.map((s) => `${s.opcode},${s.args};`).join("\n");
  const res = await api(`/api/canvases/${state.currentCanvas}/statements`, {
    method: "POST",
    body: JSON.stringify({ program }),
  });
  await reloadStatements();
  // Select the newly-appended copies (last N statements after reload).
  const all = state.statements.sort((a, b) => a.seq - b.seq);
  const newIds = all.slice(-stmts.length).map((s) => s.id);
  state.selectedIds = new Set(newIds);
  renderStatementList();
  showEditPanel();
}

async function groupSelection() {
  const ids = [...state.selectedIds];
  if (ids.length < 2) return;
  const gid = "g-" + Math.random().toString(36).slice(2, 10);
  for (const id of ids) {
    await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ group_id: gid }),
    });
  }
  await reloadStatements();
}
async function ungroupSelection() {
  const ids = [...state.selectedIds];
  for (const id of ids) {
    await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ group_id: null }),
    });
  }
  await reloadStatements();
}

async function copySelectionAsDrawlang() {
  const stmts = state.statements
    .filter((s) => state.selectedIds.has(s.id))
    .sort((a, b) => a.seq - b.seq);
  if (!stmts.length) return;
  const text = stmts.map((s) => `${s.opcode},${s.args};`).join("\n");
  try {
    await navigator.clipboard.writeText(text);
    // Small toast via edit-panel status area
    const panel = document.getElementById("copy-status");
    if (panel) { panel.textContent = `Copied ${stmts.length} statement(s)`; setTimeout(() => panel.textContent = "", 1800); }
  } catch (e) {
    // Fallback: put it in a textarea for manual copy
    const t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); document.body.removeChild(t);
  }
}

// --------------------------------------------------------------------------
// Right-rail edit panel
// --------------------------------------------------------------------------

// Shared bubble toolbar HTML for any non-empty selection.
function _bubbleToolbar(n) {
  return `
    <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
      <button data-act="rot-ccw" title="Rotate 90° counter-clockwise">↶ 90°</button>
      <button data-act="rot-cw"  title="Rotate 90° clockwise">↷ 90°</button>
      <button data-act="rot-180" title="Rotate 180°">180°</button>
      <button data-act="mir-h"   title="Mirror horizontally (flip X)">⇔ H</button>
      <button data-act="mir-v"   title="Mirror vertically (flip Y)">⇕ V</button>
      <button data-act="dup"     title="Duplicate selection">Duplicate</button>
      <button data-act="grp"     title="Group selection (assign shared group_id)" ${n < 2 ? "disabled" : ""}>Group</button>
      <button data-act="ungrp"   title="Ungroup (clear group_id)">Ungroup</button>
      <button data-act="copy"    title="Copy selection as drawlang">Copy DL</button>
      <button data-act="del"     title="Delete selection" style="color:#a12c7b">Delete</button>
    </div>
    <div id="copy-status" style="font-size:12px;color:#437a22;min-height:16px"></div>
  `;
}

// Wire the bubble toolbar's buttons.
function _wireBubbleButtons(panel) {
  panel.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const act = btn.dataset.act;
      try {
        if (act === "rot-ccw") await rotateSelection(90);
        else if (act === "rot-cw") await rotateSelection(-90);
        else if (act === "rot-180") await rotateSelection(180);
        else if (act === "mir-h") await mirrorSelection("h");
        else if (act === "mir-v") await mirrorSelection("v");
        else if (act === "dup") await duplicateSelection();
        else if (act === "grp") await groupSelection();
        else if (act === "ungrp") await ungroupSelection();
        else if (act === "copy") await copySelectionAsDrawlang();
        else if (act === "del") {
          const ids = [...state.selectedIds];
          for (const id of ids) {
            await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, { method: "DELETE" });
          }
          state.selectedIds = new Set();
          await reloadStatements();
        }
      } catch (e) {
        alert(`${act} failed: ${e.message}`);
      }
    });
  });
}

function showEditPanel() {
  const ids = [...state.selectedIds];
  const panel = $("edit-panel");
  if (ids.length === 0) {
    panel.innerHTML = '<div class="status">Click a statement above to edit.</div>';
    return;
  }
  if (ids.length > 1) {
    panel.innerHTML = `
      <div class="status">${ids.length} selected</div>
      ${_bubbleToolbar(ids.length)}
    `;
    _wireBubbleButtons(panel);
    return;
  }
  const stmt = state.statements.find((s) => s.id === ids[0]);
  if (!stmt) return;
  const currentTag = stmt.meaning_tag ?? "";
  panel.innerHTML = `
    ${_bubbleToolbar(1)}
    <label style="font-size:12px">Opcode</label>
    <input type="text" id="edit-op" value="${stmt.opcode}" style="width:100%;margin-bottom:6px" />
    <label style="font-size:12px">Args</label>
    <input type="text" id="edit-args" value="${escapeAttr(stmt.args)}" style="width:100%;margin-bottom:6px" />
    <label style="font-size:12px">Meaning tag <span style="color:#7a7974">(optional)</span></label>
    <input type="text" id="edit-meaning" value="${escapeAttr(currentTag)}" placeholder="e.g. motor/pump-101/body" style="width:100%;margin-bottom:6px" />
    <button id="edit-save" style="width:100%">Save</button>`;
  _wireBubbleButtons(panel);
  $("edit-save").addEventListener("click", async () => {
    const newTag = $("edit-meaning").value.trim();
    // Empty string → clear the tag (send explicit null so backend clears).
    const body = {
      opcode: $("edit-op").value.trim(),
      args: $("edit-args").value,
      meaning_tag: newTag === "" ? null : newTag,
    };
    await api(`/api/canvases/${state.currentCanvas}/statements/${stmt.id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    await reloadStatements();
  });
}

async function renderMeaningIndex() {
  const host = $("meaning-index");
  if (!state.currentCanvas) {
    host.innerHTML = '<div class="status">No canvas loaded.</div>';
    return;
  }
  try {
    const data = await api(`/api/canvases/${state.currentCanvas}/meaning-index`);
    const items = data.index || [];
    if (items.length === 0) {
      host.innerHTML = '<div class="status">No meaning tags yet. Set one from the edit panel.</div>';
      return;
    }
    host.innerHTML = items
      .map((r) => `<div class="meaning-row" data-tag="${escapeAttr(r.meaning_tag)}" style="display:flex;justify-content:space-between;padding:2px 4px;cursor:pointer;border-radius:3px"><span style="color:#01696f;font-family:ui-monospace,Menlo,Consolas,monospace">${escapeAttr(r.meaning_tag)}</span><span style="color:#7a7974">${r.count}</span></div>`)
      .join("");
    host.querySelectorAll(".meaning-row").forEach((el) => {
      el.addEventListener("click", async () => {
        const tag = el.getAttribute("data-tag");
        const res = await api(`/api/canvases/${state.currentCanvas}/meaning/${encodeURI(tag)}`);
        state.selectedIds = new Set(res.statements.map((s) => s.id));
        renderStatementList();
        showEditPanel();
      });
      el.addEventListener("mouseenter", () => { el.style.background = "#f0efe9"; });
      el.addEventListener("mouseleave", () => { el.style.background = ""; });
    });
  } catch (err) {
    host.innerHTML = `<div class="status err">${err.message}</div>`;
  }
}

function escapeAttr(s) {
  return String(s ?? "").replace(/"/g, "&quot;");
}

async function reloadStatements() {
  if (!state.currentCanvas) return;
  const data = await api(`/api/canvases/${state.currentCanvas}`);
  state.statements = data.statements;
  renderStatementList();
  showEditPanel();
  await renderCanvas();
  await refreshCanvasList();
  await renderMeaningIndex();
}

// --------------------------------------------------------------------------
// Command input (append statement)
// --------------------------------------------------------------------------
$("cmd-add").addEventListener("click", async () => {
  if (!state.currentCanvas) return alert("Choose a canvas first");
  const raw = $("cmd-input").value.trim();
  if (!raw) return;
  // Detect: does it look like raw drawlang (opcode,arg format) or natural language?
  const looksRaw = /^[a-z]{2},/i.test(raw);
  try {
    if (looksRaw) {
      const withSemi = raw.endsWith(";") ? raw : raw + ";";
      await api(`/api/canvases/${state.currentCanvas}/statements`, {
        method: "POST",
        body: JSON.stringify({ program: withSemi }),
      });
    } else {
      // Natural-language path
      await api("/api/nlp/translate", {
        method: "POST",
        body: JSON.stringify({ text: raw, canvas_id: state.currentCanvas }),
      });
    }
    $("cmd-input").value = "";
    await reloadStatements();
  } catch (e) {
    $("stmt-status").textContent = String(e.message);
    $("stmt-status").className = "status err";
  }
});

// Voice input via Web Speech API
$("mic-btn").addEventListener("click", () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    $("stmt-status").textContent = "Voice not supported in this browser (use Chrome/Edge)";
    $("stmt-status").className = "status err";
    return;
  }
  const rec = new SR();
  rec.lang = "en-US";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  $("stmt-status").textContent = "🎤 Listening...";
  $("stmt-status").className = "status";
  rec.onresult = (e) => {
    const heard = e.results[0][0].transcript;
    $("cmd-input").value = heard;
    $("stmt-status").textContent = `Heard: "${heard}" — click Append to run`;
  };
  rec.onerror = (e) => {
    $("stmt-status").textContent = `Voice error: ${e.error}`;
    $("stmt-status").className = "status err";
  };
  rec.start();
});
$("cmd-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("cmd-add").click();
});

// --------------------------------------------------------------------------
// Canvas create / rename / choose
// --------------------------------------------------------------------------
$("canvas-select").addEventListener("change", async (e) => {
  await loadCanvas(e.target.value);
});

// Rename current canvas. Blur or Enter commits.
async function commitRename() {
  const el = $("canvas-rename");
  const newName = el.value.trim();
  if (!newName) { el.value = ""; return; }
  if (!state.currentCanvas) { alert("Choose a canvas first"); el.value = ""; return; }
  try {
    const res = await api(`/api/canvases/${state.currentCanvas}${""}`, {
      method: "PATCH",
      body: JSON.stringify({ name: newName }),
    });
    el.value = "";
    // Server may have kept the old slug; refresh the list either way.
    const newSlug = res.canvas?.slug || state.currentCanvas;
    await refreshCanvasList();
    $("canvas-select").value = newSlug;
    state.currentCanvas = newSlug;
  } catch (e) {
    alert(e.message);
  }
}
$("canvas-rename").addEventListener("blur", commitRename);
$("canvas-rename").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); commitRename(); }
});
$("new-canvas-btn").addEventListener("click", async () => {
  const name = prompt("Canvas name?");
  if (!name) return;
  const frame_id = prompt("Frame id (a3-grid, a3-empty, blank)?", "a3-grid");
  const body = { name };
  if (frame_id && frame_id !== "blank") body.frame_id = frame_id;
  try {
    const res = await api("/api/canvases", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await refreshCanvasList();
    $("canvas-select").value = res.canvas.slug;
    await loadCanvas(res.canvas.slug);
  } catch (e) {
    alert(e.message);
  }
});

// --------------------------------------------------------------------------
// Library
// --------------------------------------------------------------------------
async function refreshLibrary() {
  const { items } = await api("/api/library");
  state.library = items;
  const list = $("library-list");
  if (!items.length) {
    list.innerHTML = '<div style="color:#7a7974;font-size:12px">Empty. Select statements → Save as symbol.</div>';
    return;
  }
  list.innerHTML = items.map((it) =>
    `<div class="lib-item" data-slug="${it.slug}" title="Click then click on canvas to drop">
      <div class="lname">${it.name}</div>
      <div class="ldesc">${it.category} · ${it.description || ""}</div>
    </div>`
  ).join("");
  list.querySelectorAll(".lib-item").forEach((el) => {
    el.addEventListener("click", () => {
      state.pendingDrop = { kind: "symbol", slug: el.dataset.slug };
      $("lib-status").textContent = `Click on canvas to place "${el.dataset.slug}"`;
      $("lib-status").className = "status ok";
      if (state.svg) state.svg.style.cursor = "copy";
    });
  });
}

async function dropLibraryHere(slug, x, y) {
  if (!state.currentCanvas) return alert("Choose a canvas first");
  try {
    await api(`/api/library/${slug}/drop/${state.currentCanvas}`, {
      method: "POST",
      body: JSON.stringify({ x, y }),
    });
    $("lib-status").textContent = `Dropped "${slug}" at (${Math.round(x)},${Math.round(y)})`;
    await reloadStatements();
  } catch (e) {
    $("lib-status").textContent = e.message;
    $("lib-status").className = "status err";
  }
}

// v0.7: Frames tab — hook the create button (element may not exist in
// older HTML snapshots; guard with a null check).
const _newFrameBtn = document.getElementById("new-frame-create");
if (_newFrameBtn) _newFrameBtn.addEventListener("click", createFrameFromSidebar);

$("save-symbol-btn").addEventListener("click", async () => {
  const name = $("save-symbol-name").value.trim();
  if (!name) return alert("Name?");
  const ids = [...state.selectedIds];
  if (!ids.length) return alert("Select statements first (click rows)");
  // Build a program from selected statements — normalized to start at 0,0.
  const selectedStmts = state.statements
    .filter((s) => state.selectedIds.has(s.id))
    .sort((a, b) => a.seq - b.seq);
  const program = selectedStmts.map((s) => `${s.opcode},${s.args};`).join("\n");
  try {
    await api("/api/library", {
      method: "POST",
      body: JSON.stringify({ name, program, category: "symbol" }),
    });
    $("save-symbol-name").value = "";
    $("lib-status").textContent = `Saved "${name}"`;
    $("lib-status").className = "status ok";
    await refreshLibrary();
  } catch (e) {
    $("lib-status").textContent = e.message;
    $("lib-status").className = "status err";
  }
});

$("render-btn").addEventListener("click", () => renderCanvas());

// --------------------------------------------------------------------------
// Export buttons
// --------------------------------------------------------------------------
function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

$("export-svg").addEventListener("click", () => {
  if (!state.currentCanvas) { alert("Choose a canvas first"); return; }
  if (!state.svgSource) { alert("Nothing rendered yet — click Render first"); return; }
  _downloadBlob(new Blob([state.svgSource], { type: "image/svg+xml" }), `${state.currentCanvas}.svg`);
});

$("export-pdf").addEventListener("click", async () => {
  if (!state.currentCanvas) { alert("Choose a canvas first"); return; }
  try {
    // Fetch the composed program (frame + body) then hand it to /export/pdf.
    const progRes = await fetch(`/api/canvases/${state.currentCanvas}/program`);
    if (!progRes.ok) throw new Error(await progRes.text());
    const program = await progRes.text();
    const res = await fetch("/export/pdf", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ program }),
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    _downloadBlob(await res.blob(), `${state.currentCanvas}.pdf`);
  } catch (err) {
    alert("PDF export failed: " + err.message);
  }
});

// Frame picker: PATCH the canvas when the user changes the frame.
$("frame-select").addEventListener("change", async (e) => {
  if (!state.currentCanvas) return;
  const frameId = e.target.value; // "" means clear
  try {
    await api(`/api/canvases/${state.currentCanvas}`, {
      method: "PATCH",
      body: JSON.stringify({ frame_id: frameId }),
    });
    await renderCanvas();
  } catch (err) {
    alert("Frame change failed: " + err.message);
  }
});

// Import: open file picker, then upload the file's text as drawlang.
$("import-btn").addEventListener("click", () => {
  if (!state.currentCanvas) { alert("Choose a canvas first"); return; }
  $("import-file").click();
});

$("import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  const lines = text.split("\n").length;
  const replace = confirm(
    `Import ${file.name} (${lines} lines) into "${state.currentCanvas}"?\n\n` +
    `OK = REPLACE canvas contents (clear existing statements first)\n` +
    `Cancel = APPEND to existing statements`
  );
  try {
    if (replace) {
      // Replace: use PUT /program which clears and re-inserts.
      const res = await fetch(`/api/canvases/${state.currentCanvas}/program`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ program: text }),
      });
      if (!res.ok) throw new Error(await res.text());
    } else {
      // Append: POST to /statements with program body.
      await api(`/api/canvases/${state.currentCanvas}/statements`, {
        method: "POST",
        body: JSON.stringify({ program: text }),
      });
    }
    await loadCanvas(state.currentCanvas);
  } catch (err) {
    alert("Import failed: " + err.message);
  } finally {
    // Reset the file input so the same file can be picked again.
    e.target.value = "";
  }
});

// --------------------------------------------------------------------------
// Startup
// --------------------------------------------------------------------------
(async () => {
  await loadFrameList();
  await refreshCanvasList();
  await refreshLibrary();
  await refreshPrimitives();
  await refreshOpcodes();
})();

// --------------------------------------------------------------------------
// Primitives (parametric library backed by editor/primitives/*.json)
// --------------------------------------------------------------------------

// Fetch the catalog once at startup; the list rarely changes at runtime.
async function refreshPrimitives() {
  try {
    const data = await api("/api/primitives");
    state.primitives = data.primitives || [];
  } catch (e) {
    state.primitives = [];
  }
  renderPrimitivesList();
}

function renderPrimitivesList() {
  const list = $("primitives-list");
  if (!list) return;
  if (!state.primitives.length) {
    list.innerHTML = '<div style="color:#7a7974;font-size:12px">No primitives loaded.</div>';
    return;
  }
  // Group by category
  const byCat = {};
  for (const p of state.primitives) {
    const c = p.category || "misc";
    (byCat[c] = byCat[c] || []).push(p);
  }
  const cats = Object.keys(byCat).sort();
  list.innerHTML = cats.map((c) => `
    <div class="prim-cat">${c}</div>
    ${byCat[c].map((p) =>
      `<div class="lib-item" data-prim-id="${p.id}" title="${escapeAttr(p.description || "")}">
        <div class="lname">${p.name}</div>
        <div class="ldesc">${p.params.length} param${p.params.length === 1 ? "" : "s"}</div>
      </div>`
    ).join("")}
  `).join("");
  list.querySelectorAll(".lib-item[data-prim-id]").forEach((el) => {
    el.addEventListener("click", () => openPrimitiveModal(el.dataset.primId));
  });
}

// ---- tab switching ----
//
// v0.7: Primitives = pure v0.6 opcodes from /api/opcodes. Symbols = a
// two-section panel: composed parametric shapes (the pre-v0.7 8 JSON
// entries) + user-saved symbols from /api/library. The invented shapes
// are labelled 'demo' because they were placeholder content, not a
// curated symbol catalog.
function setSidebarTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".lib-tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  $("opcodes-list").style.display = tab === "primitives" ? "" : "none";
  $("symbols-panel").style.display = tab === "symbols" ? "" : "none";
  const framesPanel = document.getElementById("frames-panel");
  if (framesPanel) framesPanel.style.display = tab === "frames" ? "" : "none";
  if (tab === "frames") refreshFramesSidebar();
}

// v0.7 Frames tab — list, create, delete, and edit fields. Uses the
// DB-backed /api/frames.
async function refreshFramesSidebar() {
  const host = $("frames-list");
  if (!host) return;
  try {
    const d = await api("/api/frames");
    if (!d.frames || d.frames.length === 0) {
      host.innerHTML = '<div class="status">No frames yet.</div>';
      return;
    }
    host.innerHTML = d.frames.map((f) => `
      <div class="frame-item" data-frame-id="${escapeAttr(f.id)}">
        <div class="prim-item frame-item-row">
          <span class="prim-name">${escapeAttr(f.name || f.id)}</span>
          <span class="prim-meta">${f.field_count || 0} fields</span>
          <button class="frame-fields-btn" data-fields="${escapeAttr(f.id)}" title="Edit fields" style="font-size:10px;padding:1px 4px">✎</button>
          <button class="frame-del" data-del="${escapeAttr(f.id)}" title="Delete frame" style="font-size:10px;padding:1px 4px">✕</button>
        </div>
        <div class="frame-fields-panel" data-fields-panel="${escapeAttr(f.id)}" style="display:none"></div>
      </div>
    `).join("");
    host.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = btn.dataset.del;
        if (!confirm(`Delete frame "${id}"? Canvases using it keep their frame_id.`)) return;
        await api(`/api/frames/${encodeURIComponent(id)}`, { method: "DELETE" });
        await refreshFramesSidebar();
        await loadFrameList();
      });
    });
    host.querySelectorAll("[data-fields]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openFrameFieldsEditor(btn.dataset.fields);
      });
    });
  } catch (e) {
    host.innerHTML = `<div class="status err">${escapeAttr(e.message)}</div>`;
  }
}

// v0.7: inline fields editor — shown in-line under the frame row so users
// can add/edit/delete field metadata without leaving the sidebar. Each row
// exposes name, description, default, x, y. Save PATCHes the whole array
// (backend replaces fields_json in one go).
async function openFrameFieldsEditor(frameId) {
  const panel = document.querySelector(`[data-fields-panel="${cssEsc(frameId)}"]`);
  if (!panel) return;
  if (panel.style.display !== "none") {
    panel.style.display = "none";
    panel.innerHTML = "";
    return;
  }
  panel.style.display = "";
  panel.innerHTML = '<div class="status">Loading fields…</div>';
  let data;
  try { data = await api(`/api/frames/${encodeURIComponent(frameId)}`); }
  catch (e) { panel.innerHTML = `<div class="status err">${escapeAttr(e.message)}</div>`; return; }

  const fields = Array.isArray(data.fields) ? [...data.fields] : [];

  const render = () => {
    panel.innerHTML = `
      <div class="frame-fields-editor">
        <div class="frame-fields-head">
          <span>name</span><span>default</span><span>x</span><span>y</span><span></span>
        </div>
        ${fields.map((f, i) => `
          <div class="frame-fields-row" data-idx="${i}">
            <input class="ff-name" type="text" value="${escapeAttr(f.name || "")}" placeholder="name" />
            <input class="ff-def"  type="text" value="${escapeAttr(f.default || "")}" placeholder="default" />
            <input class="ff-x"    type="number" step="0.5" value="${escapeAttr(f.x ?? 0)}" />
            <input class="ff-y"    type="number" step="0.5" value="${escapeAttr(f.y ?? 0)}" />
            <button class="ff-del" data-del-idx="${i}" title="Delete field">✕</button>
          </div>
        `).join("")}
        <div class="frame-fields-actions">
          <button class="ff-add">+ Add field</button>
          <button class="ff-save primary">Save</button>
          <button class="ff-cancel">Cancel</button>
          <span class="ff-status"></span>
        </div>
      </div>
    `;

    panel.querySelector(".ff-add").addEventListener("click", () => {
      fields.push({ name: "", default: "", x: 0, y: 0, editable: true });
      render();
    });
    panel.querySelector(".ff-cancel").addEventListener("click", () => {
      panel.style.display = "none"; panel.innerHTML = "";
    });
    panel.querySelectorAll("[data-del-idx]").forEach((b) => {
      b.addEventListener("click", () => {
        fields.splice(parseInt(b.dataset.delIdx), 1);
        render();
      });
    });
    panel.querySelector(".ff-save").addEventListener("click", async () => {
      // Read every row into the fields[] array.
      const rows = panel.querySelectorAll(".frame-fields-row");
      const out = [];
      for (const row of rows) {
        const name = row.querySelector(".ff-name").value.trim();
        if (!name) continue;   // skip blank rows
        out.push({
          name,
          default: row.querySelector(".ff-def").value,
          x: parseFloat(row.querySelector(".ff-x").value) || 0,
          y: parseFloat(row.querySelector(".ff-y").value) || 0,
          editable: true,
        });
      }
      const status = panel.querySelector(".ff-status");
      status.textContent = "Saving…";
      status.className = "ff-status";
      try {
        await api(`/api/frames/${encodeURIComponent(frameId)}`, {
          method: "PATCH",
          body: JSON.stringify({ fields: out }),
        });
        status.textContent = "Saved.";
        status.className = "ff-status ok";
        await refreshFramesSidebar();
      } catch (e) {
        status.textContent = e.message;
        status.className = "ff-status err";
      }
    });
  };
  render();
}

function cssEsc(s) {
  // Simple CSS.escape polyfill for attr selectors on frame ids.
  return String(s).replace(/("|\\)/g, "\\$1");
}

async function createFrameFromSidebar() {
  const id = $("new-frame-id").value.trim();
  const name = $("new-frame-name").value.trim();
  const dl = $("new-frame-dl").value;
  const status = $("frames-status");
  if (!id || !name || !dl.trim()) {
    status.textContent = "id, name and drawlang are all required.";
    status.className = "status err";
    return;
  }
  try {
    await api("/api/frames", {
      method: "POST",
      body: JSON.stringify({ id, name, drawlang: dl, fields: [], source: "user" }),
    });
    status.textContent = `Created ${id}.`;
    status.className = "status ok";
    $("new-frame-id").value = "";
    $("new-frame-name").value = "";
    $("new-frame-dl").value = "";
    await refreshFramesSidebar();
    await loadFrameList();
  } catch (e) {
    status.textContent = e.message;
    status.className = "status err";
  }
}



// ---- modal ----

let _modalPrim = null;         // {id, name, description, params, template...}
let _modalOpcode = null;       // v0.7: currently-loaded opcode entry, if any
let _modalPreviewTimer = null;

async function openPrimitiveModal(primId) {
  try {
    const { primitive } = await api(`/api/primitives/${primId}`);
    _modalPrim = primitive;
  } catch (e) {
    alert("Load primitive failed: " + e.message);
    return;
  }
  $("prim-modal-title").textContent = _modalPrim.name || primId;
  $("prim-modal-desc").textContent = _modalPrim.description || "";
  _renderModalForm(_modalPrim);
  _schedulePreview();
  $("prim-modal").classList.add("open");
}

function closePrimitiveModal() {
  $("prim-modal").classList.remove("open");
  _modalPrim = null;
  _modalOpcode = null;
  $("prim-modal-preview").innerHTML = '<div style="color:#7a7974;font-size:12px">Preview</div>';
}

function _renderModalForm(prim) {
  const form = $("prim-modal-form");
  if (!prim.params || !prim.params.length) {
    form.innerHTML = '<div style="color:#7a7974;font-size:12px">No parameters.</div>';
    return;
  }
  form.innerHTML = prim.params.map((p) => {
    const id = `prim-p-${p.name}`;
    const def = p.default ?? "";
    if (p.type === "select") {
      const opts = (p.options || []).map((o) =>
        `<option value="${escapeAttr(o)}"${o === p.default ? " selected" : ""}>${o}</option>`
      ).join("");
      return `<div class="form-row">
        <label for="${id}">${p.label || p.name}</label>
        <select id="${id}" data-name="${p.name}" data-type="select">${opts}</select>
      </div>`;
    }
    if (p.type === "boolean") {
      return `<div class="form-row">
        <label for="${id}">${p.label || p.name}</label>
        <input id="${id}" data-name="${p.name}" data-type="boolean" type="checkbox"${p.default ? " checked" : ""} />
      </div>`;
    }
    const numAttrs = p.type === "number"
      ? ` step="1"${p.min != null ? ` min="${p.min}"` : ""}${p.max != null ? ` max="${p.max}"` : ""}`
      : "";
    const inputType = p.type === "number" ? "number" : "text";
    return `<div class="form-row">
      <label for="${id}">${p.label || p.name}</label>
      <input id="${id}" data-name="${p.name}" data-type="${p.type || "text"}"
             type="${inputType}" value="${escapeAttr(String(def))}"${numAttrs} />
    </div>`;
  }).join("");
  // Debounced preview on any input change
  form.querySelectorAll("input, select").forEach((el) => {
    el.addEventListener("input", _schedulePreview);
    el.addEventListener("change", _schedulePreview);
  });
}

function _collectFormValues() {
  const out = {};
  document.querySelectorAll("#prim-modal-form [data-name]").forEach((el) => {
    const name = el.dataset.name;
    const type = el.dataset.type;
    if (type === "number") {
      const v = el.value;
      if (v !== "") out[name] = Number(v);
    } else if (type === "boolean") {
      out[name] = el.checked;
    } else {
      out[name] = el.value;
    }
  });
  return out;
}

function _schedulePreview() {
  if (_modalPreviewTimer) clearTimeout(_modalPreviewTimer);
  _modalPreviewTimer = setTimeout(_renderModalPreview, 250);
}

async function _renderModalPreview() {
  if (!_modalPrim) return;
  const values = _collectFormValues();
  const preview = $("prim-modal-preview");
  try {
    // Expand: params -> drawlang
    const expand = await api(`/api/primitives/${_modalPrim.id}/expand`, {
      method: "POST",
      body: JSON.stringify({ values }),
    });
    // Render: drawlang -> SVG (via canvas render, using a scratch canvas
    // would create a canvas per keystroke; we render via the render helper
    // that accepts raw program text).
    const svg = await _renderProgramToSvg(expand.drawlang);
    preview.innerHTML = svg || '<div style="color:#a12c7b;font-size:12px">No output</div>';
  } catch (e) {
    preview.innerHTML = `<div style="color:#a12c7b;font-size:12px">${escapeAttr(e.message)}</div>`;
  }
}

// Render a bare drawlang program to SVG via a scratch endpoint. We use the
// same /export/pdf machinery in reverse? — no; call a lightweight render
// helper. Since no such endpoint exists yet, we use a scratch canvas.
async function _renderProgramToSvg(program) {
  // Use the existing scratch-render endpoint if available.
  try {
    const r = await fetch("/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program, backend: "svg" }),
    });
    if (r.ok) {
      const data = await r.json();
      if (data.ok && data.output) return data.output;
      if (data.error) return `<div style="color:#a12c7b;font-size:12px">${data.error}</div>`;
    }
  } catch (e) { /* fallthrough */ }
  return "";
}

// Place button: sets pendingDrop and closes the modal. User clicks canvas
// to complete the drop at a chosen position (matches library-item flow).
function _onPlaceClick() {
  if (!_modalPrim) return;
  const values = _collectFormValues();
  state.pendingDrop = { kind: "primitive", id: _modalPrim.id, values };
  $("lib-status").textContent = `Click on canvas to place "${_modalPrim.name}"`;
  $("lib-status").className = "status ok";
  if (state.svg) state.svg.style.cursor = "copy";
  closePrimitiveModal();
}

// Actually drop a primitive at (x, y). Expands server-side, then appends
// as ``ma,x,y; <template>`` in one program POST so the primitive lands at
// the click position.
async function dropPrimitiveHere(primId, values, x, y) {
  if (!state.currentCanvas) return alert("Choose a canvas first");
  try {
    const expand = await api(`/api/primitives/${primId}/expand`, {
      method: "POST",
      body: JSON.stringify({ values }),
    });
    // Move-absolute to the click, then run the expanded program.
    const program = `ma,${Math.round(x)},${Math.round(y)};\n${expand.drawlang}`;
    await api(`/api/canvases/${state.currentCanvas}/statements`, {
      method: "POST",
      body: JSON.stringify({ program }),
    });
    // Attach the meaning_tag to the LAST inserted ma statement (the anchor).
    // Fetch fresh statements, find the ma we just inserted, PATCH it.
    await reloadStatements();
    const after = state.statements.sort((a, b) => a.seq - b.seq);
    const anchor = [...after].reverse()
      .find((s) => s.opcode === "ma" && s.args === `${Math.round(x)},${Math.round(y)}`);
    if (anchor) {
      await api(`/api/canvases/${state.currentCanvas}/statements/${anchor.id}`, {
        method: "PATCH",
        body: JSON.stringify({ meaning_tag: expand.meaning_tag }),
      });
      await reloadStatements();
    }
    $("lib-status").textContent = `Dropped "${primId}" at (${Math.round(x)},${Math.round(y)})`;
    $("lib-status").className = "status ok";
  } catch (e) {
    $("lib-status").textContent = e.message;
    $("lib-status").className = "status err";
  }
}

// Wire modal buttons + tab switching once at load.
(function _wirePrimitivesUi() {
  document.querySelectorAll(".lib-tab").forEach((el) => {
    el.addEventListener("click", () => setSidebarTab(el.dataset.tab));
  });
  $("prim-modal-close").addEventListener("click", closePrimitiveModal);
  $("prim-modal-cancel").addEventListener("click", closePrimitiveModal);
  $("prim-modal-place").addEventListener("click", _onPlaceClick);
  // Backdrop click closes the modal (but not clicks inside .modal)
  $("prim-modal").addEventListener("click", (e) => {
    if (e.target.id === "prim-modal") closePrimitiveModal();
  });
})();


// --------------------------------------------------------------------------
// Opcodes — the REAL primitives (v0.7)
//
// The Primitives tab lists v0.6 opcodes directly, one editable row each.
// No composition. No invented shapes. Clicking a row opens the arg form
// pre-filled with the opcode's spec defaults; Place sets pendingDrop and
// the next canvas click drops it as `<opcode>,<args>;` at that position.
//
// Rendered SVG elements get data-statement-id so we can round-trip clicks
// back to the source row (see selection module below).
// --------------------------------------------------------------------------

async function refreshOpcodes() {
  try {
    const data = await api("/api/opcodes");
    state.opcodes = data.opcodes || [];
  } catch (e) {
    state.opcodes = [];
  }
  renderOpcodesList();
}

function renderOpcodesList() {
  const list = $("opcodes-list");
  if (!list) return;
  if (!state.opcodes.length) {
    list.innerHTML = '<div style="color:#7a7974;font-size:12px">No opcodes loaded.</div>';
    return;
  }
  // Group by 'core' vs 'extension' — mirrors spec §6 vs §7.
  const byGroup = { core: [], extension: [] };
  for (const op of state.opcodes) (byGroup[op.group] || byGroup.core).push(op);
  const label = { core: "Core (§6)", extension: "Extensions (§7)" };
  const html = ["core", "extension"].map((g) => {
    if (!byGroup[g].length) return "";
    return `<div class="prim-cat">${label[g]}</div>${
      byGroup[g].map((op) =>
        `<div class="lib-item" data-opcode="${op.opcode}" title="${escapeAttr(op.description || "")}">
          <div class="lname"><code>${op.opcode}</code> — ${op.name}</div>
          <div class="ldesc">${op.args.map(a => a.name).join(", ")}</div>
        </div>`
      ).join("")
    }`;
  }).join("");
  list.innerHTML = html;
  list.querySelectorAll(".lib-item[data-opcode]").forEach((el) => {
    el.addEventListener("click", () => openOpcodeModal(el.dataset.opcode));
  });
}

// Reuse the primitive modal chrome for opcodes — same form layout, same
// preview logic; the only difference is that placement bypasses /expand
// and posts a raw `<opcode>,<args>;` statement. `_modalOpcode` is
// declared above (near `_modalPrim`).

async function openOpcodeModal(opcode) {
  try {
    const d = await api(`/api/opcodes/${opcode}`);
    _modalOpcode = d.opcode;
  } catch (e) {
    alert("Load opcode failed: " + e.message);
    return;
  }
  _modalPrim = null;  // ensure primitive-modal state doesn't leak in
  $("prim-modal-title").textContent = `${_modalOpcode.opcode} — ${_modalOpcode.name}`;
  $("prim-modal-desc").textContent = _modalOpcode.description || "";
  _renderOpcodeForm(_modalOpcode);
  _scheduleOpcodePreview();
  $("prim-modal").classList.add("open");
}

function _renderOpcodeForm(op) {
  const form = $("prim-modal-form");
  form.innerHTML = op.args.map((a) => {
    const id = `op-arg-${a.name}`;
    const isText = a.type === "text";
    const inputType = isText ? "text" : "number";
    return `<div class="form-row">
      <label for="${id}">${a.name}</label>
      <input id="${id}" data-name="${a.name}" data-type="${a.type}"
             type="${inputType}" value="${escapeAttr(String(a.default))}" />
    </div>`;
  }).join("");
  form.querySelectorAll("input").forEach((el) => {
    el.addEventListener("input", _scheduleOpcodePreview);
  });
}

function _collectOpcodeArgs() {
  const out = [];
  document.querySelectorAll("#prim-modal-form [data-name]").forEach((el) => {
    out.push({ name: el.dataset.name, type: el.dataset.type, value: el.value });
  });
  return out;
}

function _formatOpcodeStatement(opcode, args) {
  // Emit args in declared order. Integers stringify verbatim; text passes
  // through untouched (grammar allows unquoted text at the last position
  // of tx / po; if a spec revision tightens that, quote here.)
  const parts = args.map(a => a.value);
  return `${opcode},${parts.join(",")};`;
}

function _scheduleOpcodePreview() {
  if (_modalPreviewTimer) clearTimeout(_modalPreviewTimer);
  _modalPreviewTimer = setTimeout(_renderOpcodePreview, 250);
}

async function _renderOpcodePreview() {
  if (!_modalOpcode) return;
  const args = _collectOpcodeArgs();
  // Prepend a `ma,0,0` so the pen is anchored to the preview origin,
  // regardless of what the opcode does.
  const program = `ma,0,0;\n${_formatOpcodeStatement(_modalOpcode.opcode, args)}`;
  try {
    const svg = await _renderProgramToSvg(program);
    $("prim-modal-preview").innerHTML = svg ||
      '<div style="color:#7a7974;font-size:12px">(no visible mark)</div>';
  } catch (e) {
    $("prim-modal-preview").innerHTML =
      `<div style="color:#a12c7b;font-size:12px">${escapeAttr(e.message)}</div>`;
  }
}

// (_modalOpcode declared with _modalPrim above)

// Placement flow: Place button sets state.pendingDrop and closes the modal;
// the next click on the canvas drops the statement at that paper coordinate.
function _onPlaceClickOpcode() {
  if (!_modalOpcode) return;
  const args = _collectOpcodeArgs();
  state.pendingDrop = { kind: "opcode", opcode: _modalOpcode.opcode, args };
  $("lib-status").textContent = `Click on canvas to place "${_modalOpcode.opcode}"`;
  $("lib-status").className = "status ok";
  if (state.svg) state.svg.style.cursor = "copy";
  closePrimitiveModal();
}

async function dropOpcodeHere(opcode, args, x, y) {
  if (!state.currentCanvas) return alert("Choose a canvas first");
  // Some opcodes are pen moves in their own right (ma sets absolute pen
  // position). We always anchor the drop by inserting a ma,x,y first so
  // the semantics of the placed opcode start from the click point.
  const stmt = _formatOpcodeStatement(opcode, args);
  const program = `ma,${Math.round(x)},${Math.round(y)};\n${stmt}`;
  try {
    await api(`/api/canvases/${state.currentCanvas}/statements`, {
      method: "POST",
      body: JSON.stringify({ program }),
    });
    await reloadStatements();
    $("lib-status").textContent =
      `Placed ${opcode} at (${Math.round(x)},${Math.round(y)})`;
    $("lib-status").className = "status ok";
  } catch (e) {
    $("lib-status").textContent = e.message;
    $("lib-status").className = "status err";
  }
}

// Overwrite the modal Place-button binding so it dispatches to the opcode
// or primitive flow depending on which one populated the modal.
(function _rewirePlaceButton() {
  const btn = $("prim-modal-place");
  if (!btn) return;
  // Remove any previously-attached place handlers by replacing the node.
  const fresh = btn.cloneNode(true);
  btn.parentNode.replaceChild(fresh, btn);
  fresh.addEventListener("click", () => {
    if (_modalOpcode) return _onPlaceClickOpcode();
    if (_modalPrim) return _onPlaceClick();
  });
})();


// --------------------------------------------------------------------------
// v0.7 floating cursor bubble
//
// A compact readout that follows the mouse whenever there is at least one
// selected canvas statement. Shows: current paper coordinates, the
// selected statement's opcode+args, and the transform buttons. Restored
// from commit 74de1c7 but wired to the new bidirectional selection
// model (state.selectedIds is the single source of truth).
//
// Design notes:
// - The bubble is a plain fixed-positioned DOM node, not an SVG overlay.
//   That keeps it independent of the drawing viewBox and lets us reuse
//   normal HTML buttons.
// - We hide it when no statement is selected. Multi-select shows a
//   summary ("3 selected") in the info line.
// - Buttons dispatch to the same transform actions the sidebar toolbar
//   uses; no separate code path.
// --------------------------------------------------------------------------

(function _wireCursorBubble() {
  const bubble = document.getElementById("cursor-bubble");
  if (!bubble) return;
  const cbCoord = document.getElementById("cb-coord");
  const cbInfo = document.getElementById("cb-info");
  const cbPin = document.getElementById("cb-pin");
  const cbClose = document.getElementById("cb-close");

  // The bubble is PINNED by default (default position: top-right of the
  // canvas area). It never follows the mouse unless the user clicks the
  // pin button off. It can also be closed with ✕, and hides on Escape;
  // it comes back on the next selection change.
  let userHidden = false;      // true after × or Escape until a new selection
  let userMoved = false;       // true once dragged; disables auto-anchor
  let lastMouseX = 0;
  let lastMouseY = 0;

  function isPinned() { return bubble.dataset.pinned !== "false"; }

  function anchorToSelection() {
    // Position near the first-selected SVG element's bbox. If none,
    // top-right corner of the canvas area.
    if (userMoved) return;
    const ids = [...state.selectedIds];
    if (ids.length && state.svg) {
      const el = state.svg.querySelector(`[data-statement-id="${ids[0]}"]`);
      if (el && el.getBoundingClientRect) {
        const r = el.getBoundingClientRect();
        const bw = bubble.offsetWidth || 200;
        const bh = bubble.offsetHeight || 100;
        // Prefer top-right of the selection, fall back if it clips.
        let x = Math.min(r.right + 12, window.innerWidth - bw - 12);
        let y = Math.max(8, r.top - bh - 12);
        if (y < 8) y = Math.min(r.bottom + 12, window.innerHeight - bh - 12);
        bubble.style.left = `${x}px`;
        bubble.style.top = `${y}px`;
        return;
      }
    }
    // Fallback: pinned to the top-right of the canvas area.
    const host = document.getElementById("svg-host") || document.body;
    const r = host.getBoundingClientRect();
    const bw = bubble.offsetWidth || 200;
    bubble.style.left = `${Math.max(8, r.right - bw - 16)}px`;
    bubble.style.top = `${r.top + 12}px`;
  }

  function followMouse() {
    const pad = 16;
    const rect = bubble.getBoundingClientRect();
    let x = lastMouseX + pad;
    let y = lastMouseY + pad;
    if (x + rect.width > window.innerWidth - 8) x = lastMouseX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = lastMouseY - rect.height - pad;
    bubble.style.left = `${Math.max(4, x)}px`;
    bubble.style.top = `${Math.max(4, y)}px`;
  }

  function updateContent(paperX, paperY) {
    if (typeof paperX === "number" && typeof paperY === "number") {
      cbCoord.textContent = `x: ${Math.round(paperX)}  y: ${Math.round(paperY)}`;
    }
    const ids = [...state.selectedIds];
    if (ids.length === 0) {
      cbInfo.textContent = "";
      return;
    }
    if (ids.length === 1) {
      const s = state.statements.find((x) => x.id === ids[0]);
      cbInfo.textContent = s ? `${s.opcode},${s.args}` : "";
    } else {
      cbInfo.textContent = `${ids.length} statements selected`;
    }
  }

  function shouldShow() {
    return !userHidden && state.selectedIds && state.selectedIds.size > 0;
  }

  // ---- Mouse tracking (only used when NOT pinned) ----
  document.addEventListener("mousemove", (e) => {
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    if (state.svg) {
      try {
        const p = svgPoint(state.svg, e);
        updateContent(p.x, -p.y);
      } catch { /* out of svg */ }
    }
    if (isPinned() || bubble.contains(e.target)) return;
    if (!shouldShow()) { bubble.style.display = "none"; return; }
    bubble.style.display = "";
    followMouse();
  });

  // React to selection changes even if the mouse is still. Hook the
  // shared apply function.
  const _origApply = window.applySelectionHighlights || applySelectionHighlights;
  window.applySelectionHighlights = function () {
    _origApply();
    userHidden = false;   // new selection un-hides
    userMoved = false;    // new selection re-anchors
    if (!shouldShow()) { bubble.style.display = "none"; return; }
    updateContent();
    bubble.style.display = "";
    if (isPinned()) anchorToSelection();
    else followMouse();
  };

  // ---- Titlebar controls ----
  cbPin.addEventListener("click", () => {
    const nowPinned = !isPinned();
    bubble.dataset.pinned = nowPinned ? "true" : "false";
    if (nowPinned) { userMoved = false; anchorToSelection(); }
  });
  cbClose.addEventListener("click", () => {
    userHidden = true;
    bubble.style.display = "none";
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && bubble.style.display !== "none") {
      userHidden = true;
      bubble.style.display = "none";
    }
  });

  // ---- Drag by the titlebar handle ----
  const handle = bubble.querySelector(".cb-drag-handle");
  let drag = null;
  handle.addEventListener("mousedown", (e) => {
    const r = bubble.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    bubble.classList.add("dragging");
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!drag) return;
    bubble.style.left = `${Math.max(4, e.clientX - drag.dx)}px`;
    bubble.style.top = `${Math.max(4, e.clientY - drag.dy)}px`;
    userMoved = true;
  });
  document.addEventListener("mouseup", () => {
    if (drag) { drag = null; bubble.classList.remove("dragging"); }
  });

  // Wire the transform buttons — dispatch identical to the sidebar toolbar.
  bubble.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const act = btn.dataset.act;
      try {
        if (act === "rot-ccw") await rotateSelection(90);
        else if (act === "rot-cw") await rotateSelection(-90);
        else if (act === "rot-180") await rotateSelection(180);
        else if (act === "mir-h") await mirrorSelection("h");
        else if (act === "mir-v") await mirrorSelection("v");
        else if (act === "dup") await duplicateSelection();
        else if (act === "copy") await copySelectionAsDrawlang();
        else if (act === "del") {
          const ids = [...state.selectedIds];
          for (const id of ids) {
            await api(`/api/canvases/${state.currentCanvas}/statements/${id}`,
                      { method: "DELETE" });
          }
          state.selectedIds = new Set();
          await reloadStatements();
        }
      } catch (err) {
        alert(`${act} failed: ${err.message}`);
      }
    });
  });
})();
