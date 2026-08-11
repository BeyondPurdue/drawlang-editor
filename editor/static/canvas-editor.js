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
  renderStatementList();
  await renderCanvas();
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
  svg.addEventListener("mousemove", (e) => {
    const p = svgPoint(svg, e);
    $("coord-hud").textContent = `x: ${Math.round(p.x)}  y: ${Math.round(p.y)}`;
  });
  svg.addEventListener("click", (e) => {
    // If a library item is being dropped, place it here.
    if (state.pendingDrop) {
      const p = svgPoint(svg, e);
      dropLibraryHere(state.pendingDrop, p.x, p.y);
      state.pendingDrop = null;
      svg.style.cursor = "crosshair";
    }
  });
}

function svgPoint(svg, evt) {
  const pt = svg.createSVGPoint();
  pt.x = evt.clientX;
  pt.y = evt.clientY;
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  const inv = ctm.inverse();
  return pt.matrixTransform(inv);
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
      <button id="delete-selection" style="width:100%">Delete selection</button>`;
    $("delete-selection").addEventListener("click", async () => {
      for (const id of ids) {
        await api(`/api/canvases/${state.currentCanvas}/statements/${id}`, {
          method: "DELETE",
        });
      }
      state.selectedIds = new Set();
      await reloadStatements();
    });
    return;
  }
  const stmt = state.statements.find((s) => s.id === ids[0]);
  if (!stmt) return;
  const currentTag = stmt.meaning_tag ?? "";
  panel.innerHTML = `
    <label style="font-size:12px">Opcode</label>
    <input type="text" id="edit-op" value="${stmt.opcode}" style="width:100%;margin-bottom:6px" />
    <label style="font-size:12px">Args</label>
    <input type="text" id="edit-args" value="${escapeAttr(stmt.args)}" style="width:100%;margin-bottom:6px" />
    <label style="font-size:12px">Meaning tag <span style="color:#7a7974">(optional)</span></label>
    <input type="text" id="edit-meaning" value="${escapeAttr(currentTag)}" placeholder="e.g. motor/pump-101/body" style="width:100%;margin-bottom:6px" />
    <button id="edit-save" style="width:100%">Save</button>`;
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
// Startup
// --------------------------------------------------------------------------
(async () => {
  await refreshCanvasList();
  await refreshLibrary();
})();
