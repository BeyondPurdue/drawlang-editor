// Canvas editor — talks to /api/canvases and /api/library

const $ = (id) => document.getElementById(id);

const state = {
  canvases: [],
  currentCanvas: null,       // slug
  statements: [],
  selectedIds: new Set(),    // for multi-select
  cursorId: null,            // v0.7.2 text-editor cursor row (statement id)
  library: [],
  primitives: [],
  opcodes: [],
  activeTab: "primitives",   // sidebar tab: 'primitives' | 'symbols'
  // pendingDrop: null | {kind: 'symbol', slug} | {kind: 'primitive', id, values}
  pendingDrop: null,
  svg: null,
  vbox: null,                // viewBox as [x,y,w,h]
  zoom: 1,                   // v0.7.8 CSS scale factor on #svg-host
};

// v0.7.8 — canvas zoom (CSS transform on #svg-host).
// The SVG viewBox stays in paper mm; only the on-screen rendering
// scales. hookSvgEvents/svgPoint use getScreenCTM() which walks CSS
// transforms, so hit-testing stays correct at any zoom.
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 8;
function applyZoom() {
  const host = document.getElementById("svg-host");
  if (!host) return;
  const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, state.zoom || 1));
  state.zoom = z;
  host.style.transform = z === 1 ? "" : `scale(${z})`;
  const lbl = document.getElementById("zoom-label");
  if (lbl) lbl.textContent = `${Math.round(z * 100)}%`;
}
function setZoom(z) { state.zoom = z; applyZoom(); }
function zoomBy(mult) { setZoom((state.zoom || 1) * mult); }
function zoomFit() {
  const host = document.getElementById("svg-host");
  const area = host && host.parentElement;
  const svg = host && host.querySelector("svg");
  if (!host || !area || !svg) return;
  // Reset transform first so we measure the natural size.
  const prev = host.style.transform;
  host.style.transform = "";
  const areaW = area.clientWidth - 40;     // matches .canvas-area padding
  const areaH = area.clientHeight - 40;
  const svgW = svg.getBoundingClientRect().width;
  const svgH = svg.getBoundingClientRect().height;
  host.style.transform = prev;
  if (svgW <= 0 || svgH <= 0) return;
  const fx = areaW / svgW;
  const fy = areaH / svgH;
  const factor = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(fx, fy)));
  setZoom(factor);
}

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
    if (typeof refreshHistoryButtons === "function") refreshHistoryButtons();
    return;
  }
  const data = await api(`/api/canvases/${slug}`);
  state.currentCanvas = slug;
  state.statements = data.statements;
  state.selectedIds = new Set();
  state.currentFrameId = data.canvas?.frame_id || "";
  state.currentFieldValues = data.canvas?.field_values || {};
  updateFrameChip();
  const renameEl = $("canvas-rename");
  if (renameEl) renameEl.value = data.canvas?.name || "";
  renderStatementList();
  await renderCanvas();
  if (typeof refreshHistoryButtons === "function") refreshHistoryButtons();
}

// Cache of all frames { id, name, ... } for the modals; populated on init and
// after any frame binding change.
async function loadFrameList() {
  try {
    const res = await fetch("/api/frames");
    if (!res.ok) return;
    const data = await res.json();
    state.allFrames = data.frames || data;
  } catch (e) {
    console.error("frame list failed", e);
    state.allFrames = state.allFrames || [];
  }
  populateFramePickers();
  renderSidebarFramesList();
}

function populateFramePickers() {
  const frames = state.allFrames || [];
  for (const selId of ["nc-frame", "cf-frame"]) {
    const sel = $(selId);
    if (!sel) continue;
    const cur = sel.value;
    sel.innerHTML = '<option value="">— No frame (blank) —</option>';
    for (const f of frames) {
      const opt = document.createElement("option");
      opt.value = f.id || f.slug;
      opt.textContent = f.name || f.id || f.slug;
      sel.appendChild(opt);
    }
    if (cur) sel.value = cur;
  }
}

function updateFrameChip() {
  // Historical name kept; targets the new plain #frame-label span.
  const label = $("frame-label");
  const btn = $("field-values-btn");
  if (!label) return;
  const fid = state.currentFrameId || "";
  if (!fid) {
    label.textContent = "— none —";
    label.classList.add("empty");
    label.title = "This canvas has no frame bound.";
    if (btn) btn.disabled = true;
  } else {
    const f = (state.allFrames || []).find(x => (x.id || x.slug) === fid);
    const name = f ? (f.name || fid) : fid;
    label.textContent = name;
    label.classList.remove("empty");
    label.title = `Frame: ${fid}`;
    if (btn) btn.disabled = false;
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
  // The server returns {ok:false, error, error_kind, statement_index}
  // when a statement fails to parse or a semantic check fails. Surface
  // that plainly — do NOT paint an empty canvas and claim success.
  if (res && res.ok === false) {
    const idx = res.statement_index;
    const kind = res.error_kind || "RenderError";
    const msg = res.error || "render failed";
    $("svg-host").innerHTML = "";
    state.svg = null;
    state.svgSource = "";
    $("stmt-status").textContent = `${kind}: ${msg}`;
    $("stmt-status").className = "status err";
    // If the failing statement is identifiable, scroll it into view and
    // highlight it in the statements list so the user can see which row
    // is broken.
    if (typeof idx === "number") {
      const row = document.querySelector(`.stmt-row[data-seq="${idx}"]`);
      if (row) {
        row.scrollIntoView({ block: "center", behavior: "smooth" });
        row.classList.add("stmt-error");
        setTimeout(() => row.classList.remove("stmt-error"), 4000);
      }
    }
    return;
  }
  $("svg-host").innerHTML = res.output || "";
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
    addHitAreas(svg);
    hookSvgEvents(svg);
  }
  $("stmt-status").textContent = `Rendered ${state.statements.length} statements`;
  $("stmt-status").className = "status ok";
  // Re-apply any pre-existing selection to the newly rendered SVG.
  applySelectionHighlights();
  // v0.7.8 — re-apply the user's zoom level.
  applyZoom();
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

  // Attach to the host container so events always land, even on inner <g>
  // elements where getScreenCTM() can be null.
  const host = $("svg-host");

  // v0.7 selection: click = single-pick (with generous hit area, see below),
  // drag on empty area = rubber-band. Shift = add to selection.
  //
  // Threshold is in *client* pixels so it feels the same at any zoom.
  const DRAG_THRESHOLD_PX = 4;
  let downOnElement = null;   // the [data-statement-id] under mousedown, or null
  let downClient = null;      // {x,y} at mousedown in client px
  let downPaper = null;       // {x,y} at mousedown in SVG paper coords
  let downShift = false;
  let dragging = false;       // true once past threshold
  let rubber = null;          // DOM <div> rubber-band overlay
  // v0.7.7 — move-mode. Down inside an already-selected shape (no Shift)
  // starts a live translation of every selected <g>. Mouseup commits the
  // paper-space delta by calling nudgeSelection() so the server is the
  // source of truth.
  let moveMode = false;
  let moveGroups = [];

  host.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;         // left only
    if (state.pendingDrop) return;      // drop path handled in mouseup->click
    downClient = { x: e.clientX, y: e.clientY };
    downPaper = svgPoint(svg, e);
    downShift = e.shiftKey;
    downOnElement = e.target.closest("[data-statement-id]");
    dragging = false;
    moveMode = false;
    moveGroups = [];
    if (downOnElement && !downShift) {
      const id = parseInt(downOnElement.getAttribute("data-statement-id"), 10);
      if (Number.isFinite(id) && state.selectedIds && state.selectedIds.has(id)) {
        moveMode = true;
        moveGroups = Array.from(
          svg.querySelectorAll("[data-statement-id]")
        ).filter((g) => state.selectedIds.has(
          parseInt(g.getAttribute("data-statement-id"), 10)
        ));
      }
    }
  });

  document.addEventListener("mousemove", (e) => {
    if (!downClient || state.pendingDrop) return;
    const cdx = e.clientX - downClient.x;
    const cdy = e.clientY - downClient.y;
    if (!dragging && Math.hypot(cdx, cdy) < DRAG_THRESHOLD_PX) return;
    dragging = true;
    if (moveMode) {
      const p = svgPoint(svg, e);
      const dxSvg = p.x - downPaper.x;
      const dySvg = p.y - downPaper.y;
      for (const g of moveGroups) {
        g.setAttribute("transform", `translate(${dxSvg} ${dySvg})`);
      }
      return;
    }
    if (downOnElement && !downShift) return;
    if (!rubber) {
      rubber = document.createElement("div");
      rubber.className = "rubber-band";
      document.body.appendChild(rubber);
    }
    const x1 = Math.min(downClient.x, e.clientX);
    const y1 = Math.min(downClient.y, e.clientY);
    const x2 = Math.max(downClient.x, e.clientX);
    const y2 = Math.max(downClient.y, e.clientY);
    rubber.style.left = `${x1}px`;
    rubber.style.top = `${y1}px`;
    rubber.style.width = `${x2 - x1}px`;
    rubber.style.height = `${y2 - y1}px`;
  });

  document.addEventListener("mouseup", (e) => {
    if (!downClient) return;
    const wasDrag = dragging;
    const shift = downShift;
    const startedOn = downOnElement;
    const wasMove = moveMode;
    const groupsAtStart = moveGroups.slice();
    const startPaper = downPaper;
    const rect = rubber ? rubber.getBoundingClientRect() : null;
    // Clear state before we mutate selection so re-entrant events are safe.
    downClient = null;
    downPaper = null;
    downOnElement = null;
    downShift = false;
    dragging = false;
    moveMode = false;
    moveGroups = [];
    if (rubber) { rubber.remove(); rubber = null; }

    if (state.pendingDrop) return;   // click path handled in host.onclick below

    if (wasMove) {
      // Commit paper-space delta. Round to int (grammar stores integers).
      // The outer render uses transform=scale(1,-1) to flip y for print,
      // which means our SVG-space dy is the *negative* of paper-space dy.
      const p = svgPoint(svg, e);
      const dxPaper = Math.round(p.x - startPaper.x);
      const dyPaper = Math.round(p.y - startPaper.y);
      for (const g of groupsAtStart) g.removeAttribute("transform");
      if (wasDrag && (dxPaper !== 0 || dyPaper !== 0)) {
        nudgeSelection(dxPaper, -dyPaper);
      }
      return;
    }

    if (wasDrag && rect && (rect.width > DRAG_THRESHOLD_PX || rect.height > DRAG_THRESHOLD_PX)) {
      const hits = elementsIntersectingClientRect(svg, rect);
      applyMarqueeSelection(hits, shift);
      return;
    }

    // Not a drag — treat as click. Walk up the DOM from the actual target
    // to find the nearest ancestor tagged with data-statement-id. If none,
    // clear selection.
    const wrapper = startedOn || e.target.closest("[data-statement-id]");
    if (wrapper) {
      const id = parseInt(wrapper.getAttribute("data-statement-id"), 10);
      if (Number.isFinite(id)) selectStatementById(id, shift, { scroll: true });
    } else {
      selectStatementById(null, false);
    }
  });

  // The drop path stays as an onclick so it fires *after* mouseup without
  // interfering with the drag/click logic above.
  host.onclick = (e) => {
    if (!state.pendingDrop) return;
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
  };
}

// Return every [data-statement-id] wrapper fully contained within the
// given client-space rect. Strict containment (not intersect) — the user
// asked for tighter selection so we require the whole bbox to sit inside
// the marquee. Uses getBoundingClientRect on the wrapper itself so the
// check honours transforms exactly like the user sees them.
function elementsIntersectingClientRect(svg, rect) {
  const hits = new Set();
  const wrappers = svg.querySelectorAll("[data-statement-id]");
  wrappers.forEach((el) => {
    const b = el.getBoundingClientRect();
    // Skip zero-size (unrendered / detached) elements.
    if (b.width === 0 && b.height === 0) return;
    const contained = b.left   >= rect.left  &&
                      b.right  <= rect.right &&
                      b.top    >= rect.top   &&
                      b.bottom <= rect.bottom;
    if (contained) {
      const id = parseInt(el.getAttribute("data-statement-id"), 10);
      if (Number.isFinite(id)) hits.add(id);
    }
  });
  return hits;
}

function applyMarqueeSelection(idSet, additive) {
  if (!additive) state.selectedIds.clear();
  idSet.forEach((id) => state.selectedIds.add(id));
  applySelectionHighlights();
  showEditPanel();
  // Scroll the first selected row into view.
  const first = [...idSet][0];
  if (first !== undefined) scrollStmtRowIntoView(first);
}

// v0.7: give every visible geometry inside a [data-statement-id] wrapper a
// generous invisible hit target so thin lines and small marks are easy to
// click on a big canvas. We clone each visible <line>/<path>/<polyline>/
// <polygon>/<circle>/<rect> once, drop the clone BEHIND the original with
// a fat transparent stroke, and let pointer events land on it. Cheap, no
// renderer changes, works with any zoom level (stroke-width is in paper
// units so the viewer's transform scales it).
function addHitAreas(svg) {
  const HIT_STROKE = 12;   // paper units — comfortable finger/mouse target
  const wrappers = svg.querySelectorAll("[data-statement-id]");
  wrappers.forEach((wrap) => {
    // Skip if we've already processed this wrapper.
    if (wrap.querySelector(":scope > .hit-area")) return;
    const shapes = wrap.querySelectorAll("line, path, polyline, polygon, circle, rect, ellipse");
    shapes.forEach((shape) => {
      // Don't fatten filled regions — they already have a big pick area.
      const fill = shape.getAttribute("fill");
      const isFilled = fill && fill !== "none" && fill !== "transparent";
      if (isFilled) return;
      const hit = shape.cloneNode(false);
      hit.setAttribute("class", "hit-area");
      hit.setAttribute("stroke", "transparent");
      hit.setAttribute("stroke-width", String(HIT_STROKE));
      hit.setAttribute("fill", "none");
      hit.setAttribute("pointer-events", "stroke");
      // Remove any dash/style that could shrink pick area.
      hit.removeAttribute("stroke-dasharray");
      hit.removeAttribute("stroke-linecap");
      hit.removeAttribute("stroke-linejoin");
      // Insert BEFORE the visible shape so the visible stroke stays on top.
      shape.parentNode.insertBefore(hit, shape);
    });
  });
}

function scrollStmtRowIntoView(id) {
  const row = document.querySelector(`#stmt-list .stmt-row[data-id="${id}"]`);
  if (row && typeof row.scrollIntoView === "function") {
    row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// v0.7 selection helpers — single source of truth = state.selectedIds.
// The statements list, canvas SVG, and Edit Selected panel all read from
// this set. Any mutation must call `applySelectionHighlights()`.
function selectStatementById(id, additive, opts) {
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
  // v0.7: canvas → statements auto-scroll. Off by default (from stmt-list
  // clicks the row is already visible) and only requested by canvas picks.
  if (opts && opts.scroll && id !== null && id !== undefined) {
    scrollStmtRowIntoView(id);
  }
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
    el.innerHTML = '<div style="color:#7a7974">No statements yet. Press Enter, click below, or add via the command box.</div>';
    return;
  }
  // v0.7.2: text-editor mode — each row is a focusable line. tabindex="0"
  // makes rows keyboard-navigable; a lightweight cursor pointer tracks
  // which row is "current" for Enter-to-insert / ↑↓ / Backspace.
  // v0.8.1: each row exposes drag grip + insert-above / insert-below /
  // delete buttons. All three are only visible on hover / cursor; the
  // underlying APIs are the ones already used by the keyboard shortcuts
  // (POST /statements/insert, DELETE /statements/{id}).
  el.innerHTML = state.statements.map((s) => {
    const sel = state.selectedIds.has(s.id) ? " selected" : "";
    const cur = (state.cursorId === s.id) ? " cursor" : "";
    return `<div class="stmt-row${sel}${cur}" data-id="${s.id}" data-seq="${s.seq}" tabindex="0" draggable="true">
      <span class="stmt-grip" title="Drag to reorder">⋮</span>
      <span class="stmt-seq">${s.seq}</span>
      <span class="stmt-op" data-edit-op="${s.id}" title="Click to edit opcode (Enter=next line)">${escapeAttr(s.opcode)}</span>
      <span class="stmt-args" data-edit-args="${s.id}" title="Click to edit args (Enter=next line)">${escapeAttr(s.args)}</span>
      <span class="stmt-actions">
        <button data-insert-before="${s.id}" title="Insert line above (⇧Enter)">+↑</button>
        <button data-insert-after="${s.id}" title="Insert line below (Enter)">+↓</button>
        <button class="stmt-del" data-del="${s.id}" title="Delete (Del)">✕</button>
      </span>
    </div>`;
  }).join("");

  el.querySelectorAll(".stmt-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      // Don't hijack clicks on the delete X or on an active inline editor.
      if (e.target.dataset.del) return;
      if (e.target.tagName === "INPUT") return;
      const id = parseInt(row.dataset.id);
      state.cursorId = id;
      // v0.7: route through the shared selection helper so the canvas SVG,
      // statements list, and Edit Selected panel stay in sync.
      selectStatementById(id, e.shiftKey);
    });
    // v0.7.2: single-click on op/args cells starts inline edit (like clicking
    // in a text editor to place the caret in that word).
    row.querySelectorAll("[data-edit-op],[data-edit-args]").forEach((cell) => {
      cell.addEventListener("click", (e) => {
        e.stopPropagation();
        state.cursorId = parseInt(row.dataset.id);
        startInlineEdit(cell);
      });
    });
    // Keep dblclick working as a redundant path.
    row.querySelectorAll("[data-edit-op],[data-edit-args]").forEach((cell) => {
      cell.addEventListener("dblclick", (e) => { e.stopPropagation(); startInlineEdit(cell); });
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
  // v0.8.1: per-row insert-above / insert-below buttons.
  el.querySelectorAll("[data-insert-before]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.insertBefore);
      state.cursorId = id;
      await insertLineBefore(id);
    });
  });
  el.querySelectorAll("[data-insert-after]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.insertAfter);
      state.cursorId = id;
      await insertLineAfter(id);
    });
  });
  // v0.8.1: drag-to-reorder using the existing /statements/reorder API.
  wireStatementDrag(el);
  // Restore focus + cursor highlight after a re-render so keyboard flow
  // survives every reload.
  if (state.cursorId != null) {
    const cur = el.querySelector(`.stmt-row[data-id="${state.cursorId}"]`);
    if (cur && document.activeElement !== cur && !document.querySelector(".stmt-inline-edit")) {
      // Only auto-focus if focus is somewhere "neutral" (not inside an input
      // elsewhere on the page). Otherwise we'd steal focus from a search box.
      const active = document.activeElement;
      const activeTag = active && active.tagName ? active.tagName.toLowerCase() : "";
      if (activeTag !== "input" && activeTag !== "textarea" && !(active && active.isContentEditable)) {
        cur.focus({ preventScroll: true });
      }
    }
  }
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
  // Text-editor Enter: commit and add a fresh line right after this one.
  // "pendingAction" lets keydown handlers hand off to blur/commit without
  // racing the async patch call.
  let pendingAction = null;

  const commit = async () => {
    const newVal = input.value.trim();
    if (newVal !== original) {
      try {
        await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ [field]: newVal }),
        });
      } catch (err) {
        alert(`edit failed: ${err.message}`);
        pendingAction = null;
        await reloadStatements();
        return;
      }
    }
    // v0.7.2: dispatch the requested follow-up action AFTER the patch.
    if (pendingAction === "insertBelow") {
      await insertLineAfter(id);
    } else if (pendingAction === "insertAbove") {
      await insertLineBefore(id);
    } else if (pendingAction === "editArgs") {
      // Tab from opcode → args: reload then re-open the args cell.
      await reloadStatements();
      const argsCell = document.querySelector(`#stmt-list [data-edit-args="${id}"]`);
      if (argsCell) startInlineEdit(argsCell);
      return;
    } else if (pendingAction === "editOp") {
      await reloadStatements();
      const opCell = document.querySelector(`#stmt-list [data-edit-op="${id}"]`);
      if (opCell) startInlineEdit(opCell);
      return;
    } else {
      await reloadStatements();
    }
  };
  const cancel = () => renderStatementList();
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      pendingAction = e.shiftKey ? "insertAbove" : "insertBelow";
      input.blur();
    } else if (e.key === "Escape") {
      input.removeEventListener("blur", commit);
      cancel();
    } else if (e.key === "Tab") {
      e.preventDefault();
      pendingAction = e.shiftKey
        ? (field === "args" ? "editOp" : null)
        : (field === "opcode" ? "editArgs" : null);
      input.blur();
    }
  });
}

// --------------------------------------------------------------------------
// v0.7.2 text-editor helpers — insert / navigate / delete rows via API only.
// --------------------------------------------------------------------------
async function insertLineAfter(id) {
  const stmt = state.statements.find((s) => s.id === id);
  const targetSeq = stmt ? stmt.seq + 1 : state.statements.length;
  return insertLineAt(targetSeq);
}

async function insertLineBefore(id) {
  const stmt = state.statements.find((s) => s.id === id);
  const targetSeq = stmt ? stmt.seq : 0;
  return insertLineAt(targetSeq);
}

async function insertLineAt(seq) {
  if (!state.currentCanvas) return;
  // Default new-line: mr,0,0 — a valid, no-visible-effect statement that the
  // user can immediately overwrite. Same shape a blank line would have if
  // drawlang supported them.
  try {
    const res = await fetch(`/api/canvases/${state.currentCanvas}/statements/insert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seq, opcode: "mr", args: "0,0" }),
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    const data = await res.json();
    state.cursorId = data.statement.id;
    await reloadStatements();
    // Auto-open the opcode cell so the user can immediately type the real opcode.
    const opCell = document.querySelector(`#stmt-list [data-edit-op="${data.statement.id}"]`);
    if (opCell) startInlineEdit(opCell);
  } catch (err) {
    alert("Insert failed: " + err.message);
  }
}

function moveCursor(delta) {
  if (!state.statements.length) return;
  let idx = state.statements.findIndex((s) => s.id === state.cursorId);
  if (idx === -1) idx = 0;
  const next = Math.max(0, Math.min(state.statements.length - 1, idx + delta));
  state.cursorId = state.statements[next].id;
  renderStatementList();
}

async function deleteCurrentRow() {
  if (state.cursorId == null || !state.currentCanvas) return;
  const idx = state.statements.findIndex((s) => s.id === state.cursorId);
  if (idx === -1) return;
  const nextId = state.statements[idx + 1]?.id ?? state.statements[idx - 1]?.id ?? null;
  await api(`/api/canvases/${state.currentCanvas}/statements/${state.cursorId}`, { method: "DELETE" });
  state.cursorId = nextId;
  await reloadStatements();
}

// Global keyboard handler for the statements panel. Fires only when focus
// is on a .stmt-row (not on an <input>/<textarea> or the inline editor).
document.addEventListener("keydown", (e) => {
  const active = document.activeElement;
  if (!active || !active.classList || !active.classList.contains("stmt-row")) return;
  const id = parseInt(active.dataset.id);
  if (isNaN(id)) return;
  state.cursorId = id;
  if (e.key === "Enter") {
    e.preventDefault();
    // Shift+Enter = insert above, Enter = insert below.
    if (e.shiftKey) insertLineBefore(id); else insertLineAfter(id);
  } else if (e.key === "ArrowDown") {
    e.preventDefault(); moveCursor(1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault(); moveCursor(-1);
  } else if (e.key === "Backspace" || e.key === "Delete") {
    e.preventDefault(); deleteCurrentRow();
  } else if (e.key === " " || e.key === "F2") {
    // Space or F2 — spreadsheet-style "edit this cell" (opens the opcode).
    e.preventDefault();
    const opCell = active.querySelector("[data-edit-op]");
    if (opCell) startInlineEdit(opCell);
  }
});

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

// v0.7.7 — scale a statement's args by factor `k`.
// Around the selection centroid (integer-rounded so v0.6 grammar stays
// integer-only). Relative opcodes (mr/dl) scale their deltas; ma is scaled
// around the pivot so the group's centre-of-gravity stays put; rt scales
// w,h; ci scales r; bz scales every coordinate pair around the pivot; ar
// scales r (radius) and leaves the sweep alone; sp scales each polyline
// vertex around the pivot; im scales its w,h (id stays). tx untouched.
function _scaleArgs(stmt, k, pivot) {
  const a = _parseArgs(stmt.args);
  const op = stmt.opcode;
  const rnd = (v) => Math.round(v);
  if (op === "mr" || op === "dl") {
    if (typeof a[0] !== "number" || typeof a[1] !== "number") return null;
    return _joinArgs([rnd(a[0] * k), rnd(a[1] * k), ...a.slice(2)]);
  }
  if (op === "ma") {
    if (typeof a[0] !== "number" || typeof a[1] !== "number") return null;
    return _joinArgs([
      rnd(pivot.cx + (a[0] - pivot.cx) * k),
      rnd(pivot.cy + (a[1] - pivot.cy) * k),
      ...a.slice(2),
    ]);
  }
  if (op === "rt") {
    if (typeof a[0] !== "number" || typeof a[1] !== "number") return null;
    return _joinArgs([rnd(a[0] * k), rnd(a[1] * k), ...a.slice(2)]);
  }
  if (op === "ci") {
    if (typeof a[0] !== "number") return null;
    return _joinArgs([rnd(a[0] * k), ...a.slice(1)]);
  }
  if (op === "ar") {
    // ar: r, start, sweep — scale radius, keep angles.
    if (typeof a[0] !== "number") return null;
    return _joinArgs([rnd(a[0] * k), ...a.slice(1)]);
  }
  if (op === "bz") {
    // bz: cx1, cy1, cx2, cy2, ex, ey — all relative deltas from pen. Scale each.
    if (a.length < 6) return null;
    return _joinArgs([
      rnd(a[0] * k), rnd(a[1] * k),
      rnd(a[2] * k), rnd(a[3] * k),
      rnd(a[4] * k), rnd(a[5] * k),
      ...a.slice(6),
    ]);
  }
  if (op === "sp") {
    // sp: x1,y1,x2,y2,...,xn,yn — absolute polyline vertices. Scale about pivot.
    if (a.length < 2 || a.length % 2 !== 0) return null;
    const out = [];
    for (let i = 0; i < a.length; i += 2) {
      if (typeof a[i] !== "number" || typeof a[i+1] !== "number") return null;
      out.push(rnd(pivot.cx + (a[i]   - pivot.cx) * k));
      out.push(rnd(pivot.cy + (a[i+1] - pivot.cy) * k));
    }
    return _joinArgs(out);
  }
  if (op === "im") {
    // im: id, w, h — scale w,h; id untouched.
    if (a.length < 3 || typeof a[1] !== "number" || typeof a[2] !== "number") return null;
    return _joinArgs([a[0], rnd(a[1] * k), rnd(a[2] * k), ...a.slice(3)]);
  }
  // tx (angle,text) — skip. Users can edit size in the tx statement itself.
  return null;
}

async function scaleSelection(factor) {
  if (!(factor > 0)) return;
  const stmts = state.statements.filter((s) => state.selectedIds.has(s.id));
  if (!stmts.length) return;
  const pivot = _selectionCentroid(stmts);
  await _transformSelection((s) => _scaleArgs(s, factor, pivot));
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

// v0.7.5 arrow-key nudge.
//
// Rule: for each selected statement, find its anchor — the nearest
// preceding `ma` (absolute) or `mr` (relative) with seq ≤ this row's seq.
// Shift that anchor by (dx, dy). Multiple selected statements sharing the
// same anchor only shift the anchor once.
//
// Anchors that are themselves selected are shifted directly. This gives
// the expected behaviour when the user picks a whole shape (anchor + draw
// ops) or just clicks the draw op alone.
function _findAnchorFor(stmt, sortedStmts) {
  // Walk backward from this statement's index looking for ma/mr.
  const idx = sortedStmts.findIndex((s) => s.id === stmt.id);
  if (idx < 0) return null;
  for (let i = idx; i >= 0; i--) {
    const s = sortedStmts[i];
    if (s.opcode === "ma" || s.opcode === "mr") return s;
  }
  return null;
}

async function nudgeSelection(dx, dy) {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  const sorted = [...state.statements].sort((a, b) => a.seq - b.seq);
  const anchorIds = new Set();
  for (const id of ids) {
    const stmt = sorted.find((s) => s.id === id);
    if (!stmt) continue;
    const anchor = _findAnchorFor(stmt, sorted);
    if (anchor) anchorIds.add(anchor.id);
  }
  if (!anchorIds.size) {
    const status = $("lib-status");
    if (status) {
      status.textContent = "Cannot nudge — selection has no anchor (ma/mr) to shift.";
      status.className = "status err";
    }
    return;
  }
  const changed = [];
  for (const aid of anchorIds) {
    const s = sorted.find((x) => x.id === aid);
    if (!s) continue;
    const a = _parseArgs(s.args);
    if (typeof a[0] !== "number" || typeof a[1] !== "number") continue;
    // ma is absolute paper coords, mr is a delta — both add (dx,dy) to move
    // the resulting pen position by the same amount.
    changed.push({ id: aid, args: _joinArgs([a[0] + dx, a[1] + dy, ...a.slice(2)]) });
  }
  for (const c of changed) {
    await api(`/api/canvases/${state.currentCanvas}/statements/${c.id}`, {
      method: "PATCH",
      body: JSON.stringify({ args: c.args }),
    });
  }
  await reloadStatements();
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
      <button data-act="scale-up"   title="Scale up (×1.1)">+ 10%</button>
      <button data-act="scale-down" title="Scale down (÷1.1)">− 10%</button>
      <button data-act="scale-2x"   title="Double size">×2</button>
      <button data-act="scale-half" title="Half size">÷2</button>
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
        else if (act === "scale-up")   await scaleSelection(1.1);
        else if (act === "scale-down") await scaleSelection(1/1.1);
        else if (act === "scale-2x")   await scaleSelection(2);
        else if (act === "scale-half") await scaleSelection(0.5);
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
  // v0.7: keep undo/redo button state in sync with the server after any
  // reload (which is called by every mutation).
  if (typeof refreshHistoryButtons === "function") {
    refreshHistoryButtons();
  }
}

// --------------------------------------------------------------------------
// Command input (append statement, or insert after cursor when one exists)
// --------------------------------------------------------------------------
// v0.8.1: if there is a cursor row, insert the new statement after it; else
// append at the end. Same UI, same input box — semantics just track the
// keyboard flow. Uses POST /statements/insert with seq = cursor.seq + 1.
$("cmd-add").addEventListener("click", async () => {
  if (!state.currentCanvas) return alert("Choose a canvas first");
  const raw = $("cmd-input").value.trim();
  if (!raw) return;
  // Detect: does it look like raw drawlang (opcode,arg format) or natural language?
  const looksRaw = /^[a-z]{2},/i.test(raw);
  const cursorStmt = state.cursorId != null
    ? state.statements.find((s) => s.id === state.cursorId)
    : null;
  try {
    if (looksRaw) {
      // Parse "opcode,args" so we can honour cursor insert; keep the old
      // multi-statement fallback if the user pasted a whole program.
      const withSemi = raw.endsWith(";") ? raw : raw + ";";
      const singleMatch = raw.match(/^([a-z]{2})(?:,(.*))?$/i);
      if (cursorStmt && singleMatch && !raw.includes(";")) {
        await api(`/api/canvases/${state.currentCanvas}/statements/insert`, {
          method: "POST",
          body: JSON.stringify({
            seq: cursorStmt.seq + 1,
            opcode: singleMatch[1],
            args: (singleMatch[2] || "").trim(),
          }),
        });
      } else {
        await api(`/api/canvases/${state.currentCanvas}/statements`, {
          method: "POST",
          body: JSON.stringify({ program: withSemi }),
        });
      }
    } else {
      // Natural-language path.
      // v0.7.7: if there's a live selection, try selection-transform first
      // (mouse/keyboard already accept these; voice should too). Fall back
      // to the statement-creation translator otherwise.
      let handled = false;
      if (state.selectedIds && state.selectedIds.size > 0) {
        try {
          const r = await fetch("/api/nlp/selection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: raw }),
          });
          if (r.ok) {
            const j = await r.json();
            const act = j.action;
            if (act && act.op === "shift") {
              await nudgeSelection(act.dx | 0, act.dy | 0);
              handled = true;
            } else if (act && act.op === "scale") {
              await scaleSelection(Number(act.factor));
              handled = true;
            }
          }
        } catch (_) { /* fall through */ }
      }
      if (!handled) {
        await api("/api/nlp/translate", {
          method: "POST",
          body: JSON.stringify({ text: raw, canvas_id: state.currentCanvas }),
        });
      }
    }
    $("cmd-input").value = "";
    await reloadStatements();
  } catch (e) {
    $("stmt-status").textContent = String(e.message);
    $("stmt-status").className = "status err";
  }
});

// --------------------------------------------------------------------------
// v0.8.1 drag-to-reorder
// --------------------------------------------------------------------------
// One reorder API call per drop. The reorder API takes the full desired
// id order; the row's midpoint decides above-vs-below insertion.
let _dragId = null;
function wireStatementDrag(container) {
  container.querySelectorAll(".stmt-row").forEach((row) => {
    row.addEventListener("dragstart", (e) => {
      _dragId = parseInt(row.dataset.id);
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      // Firefox needs some payload for drag to fire.
      try { e.dataTransfer.setData("text/plain", String(_dragId)); } catch (_) {}
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      container.querySelectorAll(".stmt-row").forEach((r) => {
        r.classList.remove("drag-over-top", "drag-over-bot");
      });
      _dragId = null;
    });
    row.addEventListener("dragover", (e) => {
      if (_dragId == null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const rect = row.getBoundingClientRect();
      const above = (e.clientY - rect.top) < rect.height / 2;
      row.classList.toggle("drag-over-top", above);
      row.classList.toggle("drag-over-bot", !above);
    });
    row.addEventListener("dragleave", () => {
      row.classList.remove("drag-over-top", "drag-over-bot");
    });
    row.addEventListener("drop", async (e) => {
      if (_dragId == null) return;
      e.preventDefault();
      const targetId = parseInt(row.dataset.id);
      const rect = row.getBoundingClientRect();
      const above = (e.clientY - rect.top) < rect.height / 2;
      row.classList.remove("drag-over-top", "drag-over-bot");
      const draggedId = _dragId;
      _dragId = null;
      if (draggedId === targetId) return;
      // Build the new id order.
      const ids = state.statements.map((s) => s.id).filter((id) => id !== draggedId);
      const targetIdx = ids.indexOf(targetId);
      if (targetIdx === -1) return;
      const insertAt = above ? targetIdx : targetIdx + 1;
      ids.splice(insertAt, 0, draggedId);
      try {
        await api(`/api/canvases/${state.currentCanvas}/statements/reorder`, {
          method: "POST",
          body: JSON.stringify({ order: ids }),
        });
        state.cursorId = draggedId;
        await reloadStatements();
      } catch (err) {
        $("stmt-status").textContent = "Reorder failed: " + err.message;
        $("stmt-status").className = "status err";
      }
    });
  });
}

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
    $("stmt-status").textContent = `Heard: "${heard}" — click Insert to run`;
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
// v0.7.6: replace the two prompt() popups with a real modal that also lets
// the user set frame field values up front. All calls go via the /api layer.
let _ncCurrentFrameRaw = null;

function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("open");
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("open");
}

// Delegate closes for any element with data-close="<modal-id>".
document.addEventListener("click", (e) => {
  const closeId = e.target?.dataset?.close;
  if (closeId) closeModal(closeId);
});

$("new-canvas-btn").addEventListener("click", async () => {
  // Refresh cache so a frame just created in Frame Editor is visible.
  await loadFrameList();
  $("nc-name").value = "";
  $("nc-frame").value = "";
  $("nc-status").textContent = "";
  $("nc-status").className = "status";
  $("nc-fields").innerHTML =
    '<div class="fv-empty">Select a frame to see its editable fields.</div>';
  _ncCurrentFrameRaw = null;
  openModal("new-canvas-modal");
  setTimeout(() => $("nc-name").focus(), 50);
});

$("nc-frame").addEventListener("change", async () => {
  const fid = $("nc-frame").value;
  const box = $("nc-fields");
  if (!fid) {
    box.innerHTML =
      '<div class="fv-empty">No frame selected — canvas will start blank.</div>';
    _ncCurrentFrameRaw = null;
    return;
  }
  box.innerHTML = '<div class="fv-empty">Loading fields…</div>';
  try {
    const raw = await api(`/api/frames/${encodeURIComponent(fid)}/raw`);
    _ncCurrentFrameRaw = raw;
    renderFieldValueForm(box, raw.fields || [], {});
  } catch (e) {
    box.innerHTML = `<div class="fv-empty" style="color:#A12C7B">Failed to load fields: ${e.message}</div>`;
    _ncCurrentFrameRaw = null;
  }
});

$("nc-create-btn").addEventListener("click", async () => {
  const name = $("nc-name").value.trim();
  if (!name) {
    $("nc-status").textContent = "Canvas name is required.";
    $("nc-status").className = "status err";
    return;
  }
  const frame_id = $("nc-frame").value || null;
  const body = { name };
  if (frame_id) body.frame_id = frame_id;
  const values = readFieldValueForm($("nc-fields"));
  if (Object.keys(values).length > 0) body.field_values = values;
  try {
    $("nc-status").textContent = "Creating…";
    $("nc-status").className = "status";
    const res = await api("/api/canvases", {
      method: "POST",
      body: JSON.stringify(body),
    });
    closeModal("new-canvas-modal");
    await refreshCanvasList();
    $("canvas-select").value = res.canvas.slug;
    await loadCanvas(res.canvas.slug);
  } catch (e) {
    $("nc-status").textContent = e.message;
    $("nc-status").className = "status err";
  }
});

function renderFieldValueForm(container, fields, values) {
  // Renders one <label>/<input> row per editable field. Non-editable fields
  // are informational only. `values` is the current dict of user overrides.
  const editable = (fields || []).filter(f => f && f.editable !== false);
  if (editable.length === 0) {
    container.innerHTML =
      '<div class="fv-empty">This frame has no editable fields.</div>';
    return;
  }
  const rows = editable.map(f => {
    const name = f.name;
    const label = f.label || f.name;
    const def = f.default != null ? String(f.default) : "";
    const val = values && Object.prototype.hasOwnProperty.call(values, name)
      ? String(values[name]) : "";
    return `
      <div class="fv-row">
        <label title="{{${name}}}">${escapeHtml(label)}<span class="tok">{{${escapeHtml(name)}}}</span></label>
        <input type="text" data-fv-name="${escapeHtml(name)}" data-fv-default="${escapeHtml(def)}"
               value="${escapeHtml(val)}" placeholder="${escapeHtml(def) || 'default'}">
      </div>`;
  });
  container.innerHTML = rows.join("");
}

function readFieldValueForm(container) {
  // Only capture inputs with non-empty user text; empty means “use default”.
  const out = {};
  for (const inp of container.querySelectorAll('input[data-fv-name]')) {
    const name = inp.dataset.fvName;
    const v = (inp.value || "").trim();
    if (v.length > 0) out[name] = v;
  }
  return out;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// v0.7 file management: Duplicate the current canvas (deep copy including
// statements and frame binding) to a new slug via POST /duplicate.
$("dup-canvas-btn").addEventListener("click", async () => {
  if (!state.currentCanvas) { alert("Choose a canvas to duplicate first"); return; }
  const suggested = `${state.currentCanvas}-copy`;
  const slug = prompt("New canvas slug?", suggested);
  if (!slug) return;
  const name = prompt("New canvas name?", slug) || slug;
  try {
    const res = await fetch(`/api/canvases/${state.currentCanvas}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, name }),
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    const data = await res.json();
    await refreshCanvasList();
    $("canvas-select").value = data.canvas.slug;
    await loadCanvas(data.canvas.slug);
  } catch (e) {
    alert("Duplicate failed: " + e.message);
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
const _newFrameImportBtn = document.getElementById("new-frame-import-btn");
const _newFrameImportFile = document.getElementById("new-frame-import-file");
if (_newFrameImportBtn && _newFrameImportFile) {
  _newFrameImportBtn.addEventListener("click", () => _newFrameImportFile.click());
  _newFrameImportFile.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    // Fill the New-frame form with sensible defaults derived from the filename.
    const base = file.name.replace(/\.drawlang$|\.txt$/i, "")
      .toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "");
    if (!$("new-frame-id").value) $("new-frame-id").value = base;
    if (!$("new-frame-name").value) $("new-frame-name").value = base;
    $("new-frame-dl").value = text;
    e.target.value = "";
    const status = $("frames-status");
    if (status) {
      status.textContent = `Loaded ${file.name}. Review id/name and click Create frame.`;
      status.className = "status";
    }
  });
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
// v0.7.8 — Canvas zoom
// --------------------------------------------------------------------------
$("zoom-in").addEventListener("click",   () => zoomBy(1.25));
$("zoom-out").addEventListener("click",  () => zoomBy(1 / 1.25));
$("zoom-reset").addEventListener("click", () => setZoom(1));
$("zoom-fit").addEventListener("click",  () => zoomFit());

// Ctrl/Cmd + mouse wheel = zoom around the cursor.
(function _wireWheelZoom() {
  const area = document.querySelector(".canvas-area");
  if (!area) return;
  area.addEventListener("wheel", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    const host = document.getElementById("svg-host");
    if (!host) return;
    // Zoom-around-cursor: keep the pixel under the cursor fixed by
    // adjusting scrollLeft/scrollTop after the scale change.
    const before = state.zoom || 1;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const after = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, before * factor));
    if (after === before) return;
    const rect = area.getBoundingClientRect();
    // Position in scaled content space (px from host origin).
    const cx = e.clientX - rect.left + area.scrollLeft;
    const cy = e.clientY - rect.top  + area.scrollTop;
    setZoom(after);
    // Keep the same paper point under the cursor after scaling.
    const ratio = after / before;
    area.scrollLeft = cx * ratio - (e.clientX - rect.left);
    area.scrollTop  = cy * ratio - (e.clientY - rect.top);
  }, { passive: false });
})();

// Keyboard shortcuts: +/= zoom in, - zoom out, 0 = 100%, f = fit.
// Ignored while typing into form controls.
document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" ||
      (e.target && e.target.isContentEditable)) return;
  if (e.altKey) return;
  // Ctrl/Cmd+0 is the browser default; support it too as "reset".
  if ((e.ctrlKey || e.metaKey) && e.key === "0") {
    e.preventDefault(); setZoom(1); return;
  }
  if (e.ctrlKey || e.metaKey) return;
  if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomBy(1.25); }
  else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomBy(1 / 1.25); }
  else if (e.key === "0") { e.preventDefault(); setZoom(1); }
  else if (e.key === "f" || e.key === "F") { e.preventDefault(); zoomFit(); }
});

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

// v0.7: Export DrawLang — downloads the composed program (frame + body) as
// a text file so the user can reopen it later in any canvas or share it.
$("export-dl").addEventListener("click", async () => {
  if (!state.currentCanvas) { alert("Choose a canvas first"); return; }
  try {
    const res = await fetch(`/api/canvases/${state.currentCanvas}/program`);
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    const program = await res.text();
    _downloadBlob(
      new Blob([program], { type: "text/plain;charset=utf-8" }),
      `${state.currentCanvas}.drawlang`
    );
  } catch (err) {
    alert("DrawLang export failed: " + err.message);
  }
});

// v0.7: server-side Undo/Redo. Every canvas mutation snapshots the pre-state
// on the backend; these buttons call /api/canvases/{slug}/undo|redo and then
// re-render. Depths (returned by the endpoints and by GET /history) drive the
// disabled state so the buttons never lie about what's available.
async function refreshHistoryButtons() {
  const undoBtn = $("undo-btn");
  const redoBtn = $("redo-btn");
  if (!state.currentCanvas) {
    undoBtn.disabled = true; redoBtn.disabled = true;
    return;
  }
  try {
    const res = await fetch(`/api/canvases/${state.currentCanvas}/history`);
    if (!res.ok) return;
    const d = await res.json();
    undoBtn.disabled = (d.undo_depth || 0) === 0;
    redoBtn.disabled = (d.redo_depth || 0) === 0;
    undoBtn.title = `Undo (${d.undo_depth || 0} available) — Ctrl/Cmd+Z`;
    redoBtn.title = `Redo (${d.redo_depth || 0} available) — Ctrl/Cmd+Shift+Z`;
  } catch (_) { /* leave buttons in previous state on transient errors */ }
}

async function doUndo() {
  if (!state.currentCanvas) return;
  const res = await fetch(`/api/canvases/${state.currentCanvas}/undo`, { method: "POST" });
  if (!res.ok) { alert("Undo failed: " + await res.text()); return; }
  const d = await res.json();
  if (!d.ok) return refreshHistoryButtons();   // stack was empty
  await reloadStatements();   // this already re-renders the canvas
  refreshHistoryButtons();
}

async function doRedo() {
  if (!state.currentCanvas) return;
  const res = await fetch(`/api/canvases/${state.currentCanvas}/redo`, { method: "POST" });
  if (!res.ok) { alert("Redo failed: " + await res.text()); return; }
  const d = await res.json();
  if (!d.ok) return refreshHistoryButtons();
  await reloadStatements();
  refreshHistoryButtons();
}

$("undo-btn").addEventListener("click", doUndo);
$("redo-btn").addEventListener("click", doRedo);

// Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z (or Ctrl+Y) = redo. Ignore when the
// focus is inside a text input so we don't hijack the browser's own undo
// on the code editor / rename box / inline stmt edit.
document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || (e.target && e.target.isContentEditable)) return;
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  if (e.key === "z" || e.key === "Z") {
    e.preventDefault();
    if (e.shiftKey) doRedo(); else doUndo();
  } else if (e.key === "y" || e.key === "Y") {
    e.preventDefault();
    doRedo();
  }
});

// v0.7.5: arrow keys nudge the current selection by 1 paper unit (mm).
// Shift+Arrow = 10 units. Ignore when a form control has focus.
document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" ||
      (e.target && e.target.isContentEditable)) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (!state.selectedIds || !state.selectedIds.size) return;
  const step = e.shiftKey ? 10 : 1;
  let dx = 0, dy = 0;
  if (e.key === "ArrowLeft")       dx = -step;
  else if (e.key === "ArrowRight") dx =  step;
  else if (e.key === "ArrowUp")    dy = -step;
  else if (e.key === "ArrowDown")  dy =  step;
  else return;
  e.preventDefault();
  nudgeSelection(dx, dy);
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

// v0.7.6: Frame binding is set through the “change…” link next to the chip.
// The old inline <select id="frame-select"> is gone — all state.currentFrameId
// changes go through the modal + PATCH /api/canvases/{slug}.
$("change-frame-btn").addEventListener("click", async () => {
  if (!state.currentCanvas) {
    alert("Choose a canvas first.");
    return;
  }
  await loadFrameList();
  $("cf-frame").value = state.currentFrameId || "";
  $("cf-status").textContent = "";
  $("cf-status").className = "status";
  openModal("change-frame-modal");
});

$("cf-apply-btn").addEventListener("click", async () => {
  if (!state.currentCanvas) return;
  const frameId = $("cf-frame").value; // "" means clear
  try {
    $("cf-status").textContent = "Applying…";
    $("cf-status").className = "status";
    const res = await api(`/api/canvases/${state.currentCanvas}`, {
      method: "PATCH",
      body: JSON.stringify({ frame_id: frameId }),
    });
    state.currentFrameId = res.canvas?.frame_id || "";
    updateFrameChip();
    closeModal("change-frame-modal");
    await renderCanvas();
  } catch (err) {
    $("cf-status").textContent = "Frame change failed: " + err.message;
    $("cf-status").className = "status err";
  }
});

// Field values: PATCH the canvas's field_values via API.
$("field-values-btn").addEventListener("click", async () => {
  if (!state.currentCanvas) return;
  const fid = state.currentFrameId;
  if (!fid) return;
  $("fv-status").textContent = "";
  $("fv-status").className = "status";
  $("fv-frame-info").textContent = `Frame: ${fid}`;
  $("fv-fields").innerHTML = '<div class="fv-empty">Loading fields…</div>';
  openModal("fv-modal");
  try {
    const raw = await api(`/api/frames/${encodeURIComponent(fid)}/raw`);
    renderFieldValueForm($("fv-fields"), raw.fields || [], state.currentFieldValues || {});
  } catch (e) {
    $("fv-fields").innerHTML =
      `<div class="fv-empty" style="color:#A12C7B">Failed to load fields: ${escapeHtml(e.message)}</div>`;
  }
});

$("fv-save-btn").addEventListener("click", async () => {
  if (!state.currentCanvas) return;
  const values = readFieldValueForm($("fv-fields"));
  try {
    $("fv-status").textContent = "Saving…";
    $("fv-status").className = "status";
    const res = await api(`/api/canvases/${state.currentCanvas}`, {
      method: "PATCH",
      body: JSON.stringify({ field_values: values }),
    });
    state.currentFieldValues = res.canvas?.field_values || values;
    closeModal("fv-modal");
    await renderCanvas();
  } catch (err) {
    $("fv-status").textContent = "Save failed: " + err.message;
    $("fv-status").className = "status err";
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

// v0.7.6 Frames tab — read-only picker. Users bind a frame to the current
// canvas by clicking Use. To create, delete, or edit frames they open the
// dedicated Frame Editor.
async function refreshFramesSidebar() {
  await loadFrameList();
}

function renderSidebarFramesList() {
  const host = $("frames-list");
  if (!host) return;
  const frames = state.allFrames || [];
  if (frames.length === 0) {
    host.innerHTML =
      '<div class="status">No frames yet. Create one in the <a href="/frames-editor" target="_blank">Frame Editor</a>.</div>';
    return;
  }
  const boundId = state.currentFrameId || "";
  host.innerHTML = frames.map((f) => {
    const id = f.id || f.slug;
    const isBound = id === boundId;
    const name = f.name || id;
    const count = f.field_count != null ? f.field_count : 0;
    return `
      <div class="frame-item" data-frame-id="${escapeAttr(id)}">
        <div class="prim-item frame-item-row" style="display:flex;gap:6px;align-items:center;padding:4px 6px">
          <span class="prim-name" style="flex:1;overflow:hidden;text-overflow:ellipsis">${escapeAttr(name)}${isBound ? " • in use" : ""}</span>
          <span class="prim-meta" style="font-size:11px;color:#7A7974">${count} field${count === 1 ? "" : "s"}</span>
          <button class="frame-use" data-use="${escapeAttr(id)}" title="Use this frame on the current canvas" style="font-size:10px;padding:1px 6px" ${isBound || !state.currentCanvas ? "disabled" : ""}>Use</button>
        </div>
      </div>`;
  }).join("");
  host.querySelectorAll("[data-use]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.use;
      if (!state.currentCanvas) return;
      try {
        const res = await api(`/api/canvases/${state.currentCanvas}`, {
          method: "PATCH",
          body: JSON.stringify({ frame_id: id }),
        });
        state.currentFrameId = res.canvas?.frame_id || id;
        updateFrameChip();
        renderSidebarFramesList();
        await renderCanvas();
      } catch (err) {
        alert("Frame change failed: " + err.message);
      }
    });
  });
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
        <div class="prim-cat" style="margin-top:0">Frame metadata</div>
        <label style="display:block;font-size:11px;color:#7a7974">Display name</label>
        <input class="ff-frame-name" type="text" value="${escapeAttr(data.name || "")}" style="width:100%;margin-bottom:4px" />
        <label style="display:block;font-size:11px;color:#7a7974">DrawLang source</label>
        <textarea class="ff-frame-dl" rows="6" style="width:100%;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;margin-bottom:6px">${escapeAttr(data.drawlang || "")}</textarea>
        <div class="prim-cat">Editable fields</div>
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
      const newName = panel.querySelector(".ff-frame-name").value.trim() || data.name || frameId;
      const newDl = panel.querySelector(".ff-frame-dl").value;
      const status = panel.querySelector(".ff-status");
      status.textContent = "Saving…";
      status.className = "ff-status";
      try {
        await api(`/api/frames/${encodeURIComponent(frameId)}`, {
          method: "PATCH",
          body: JSON.stringify({ name: newName, drawlang: newDl, fields: out }),
        });
        status.textContent = "Saved.";
        status.className = "ff-status ok";
        await refreshFramesSidebar();
        await loadFrameList();
        // Re-render if this frame is currently bound to the canvas.
        if (state.currentCanvas && state.currentFrameId === frameId) {
          await loadCanvas(state.currentCanvas);
        }
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
        else if (act === "scale-up")   await scaleSelection(1.1);
        else if (act === "scale-down") await scaleSelection(1/1.1);
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
