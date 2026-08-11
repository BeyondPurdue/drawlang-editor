// Canvas editor — talks to /api/canvases and /api/library

const $ = (id) => document.getElementById(id);

const state = {
  canvases: [],
  currentCanvas: null,       // slug
  statements: [],
  selectedIds: new Set(),    // for multi-select
  library: [],
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
  const res = await api(`/api/canvases/${state.currentCanvas}/render`, {
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
    if (!state.pendingDrop) return;
    const p = toPaper(svgPoint(svg, e));
    dropLibraryHere(state.pendingDrop, p.x, p.y);
    state.pendingDrop = null;
    svg.style.cursor = "crosshair";
  };
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
      <span class="stmt-op">${s.opcode}</span>
      <span class="stmt-args">${s.args}</span>
      <span class="stmt-del" data-del="${s.id}" title="Delete">✕</span>
    </div>`;
  }).join("");

  el.querySelectorAll(".stmt-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.dataset.del) return;
      const id = parseInt(row.dataset.id);
      if (e.shiftKey) {
        // range from last selected to this
        if (state.selectedIds.has(id)) state.selectedIds.delete(id);
        else state.selectedIds.add(id);
      } else {
        state.selectedIds = new Set([id]);
      }
      renderStatementList();
      showEditPanel();
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
      state.pendingDrop = el.dataset.slug;
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
})();
