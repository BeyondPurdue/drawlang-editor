// v0.8.2 Frame Editor — canvas parity.
//
// Frames are stored on the server as a single `drawlang` text blob (see
// editor/app/frames.py). To give them the same statement-by-statement editor
// as canvases have (v0.8.1), the editor parses the blob into a list of
// {seq, opcode, args} rows on load, drives all UI mutations against that
// list, and re-serializes back to a string on every change. Save uses the
// existing PATCH /api/frames/{id} endpoint — no new backend.
//
// Everything goes through the JSON API. No prompt() dialogs, no direct DB
// writes, no localStorage.

const API = ''; // same-origin

const state = {
  frames: [],           // [{id, name, ...}] from /api/frames
  frameId: null,        // currently selected frame id
  loaded: null,         // last-fetched frame from API (name/drawlang/fields)
  edits: null,          // in-memory edits { name, drawlang, fields }
  activeTab: 'stmts',
  tokensDetected: [],
  // v0.8.2: statement-editor state
  statements: [],       // [{id, seq, kind, opcode, args, raw}] derived from drawlang
  cursorId: null,
  _stmtIdCounter: 1,
  _previewTimer: null,
  _dragId: null,
};

// ---------- API helpers ----------

async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(API + path, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
async function apiPatch(path, body) {
  const r = await fetch(API + path, {
    method: 'PATCH', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
async function apiDelete(path) {
  const r = await fetch(API + path, {method: 'DELETE'});
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

// ---------- Status / errors ----------

function setStatus(msg, cls='') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + cls;
}
function setFieldsError(msg) {
  const el = document.getElementById('fields-error');
  if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
  el.style.display = 'block'; el.textContent = msg;
}

// ---------- DrawLang parser / serializer (client-side) ----------
//
// Grammar (matches drawlang v0.6, see spec §3):
//   program = ( statement ";" )*
//   statement = opcode ("," argument)*
// Comment lines start with '#' and are preserved as `kind: "comment"` rows so
// nothing is lost when switching between Statements and Raw views.

function parseDrawlang(text) {
  const rows = [];
  const src = String(text || '');
  // Split by ';' but preserve interleaved comments/blank lines by processing
  // line-by-line first: comment or blank lines become comment rows; the
  // remaining text is split on ';'.
  //
  // We iterate through the source, walking every character. A leading '#' on
  // a physical line starts a comment that ends at the newline.
  const lines = src.split(/\r?\n/);
  const buf = []; // pending statement text across lines
  let bufStartLine = -1;
  for (let li = 0; li < lines.length; li++) {
    const ln = lines[li];
    const trimmed = ln.trim();
    if (trimmed.startsWith('#')) {
      // flush any pending buffered statement text first
      flushBuf();
      rows.push({
        id: state._stmtIdCounter++,
        seq: rows.length,
        kind: 'comment',
        opcode: '#',
        args: trimmed.replace(/^#\s?/, ''),
        raw: ln,
      });
      continue;
    }
    if (trimmed === '') {
      flushBuf();
      // Preserve blank lines as blank comment rows so save round-trips.
      rows.push({
        id: state._stmtIdCounter++,
        seq: rows.length,
        kind: 'blank',
        opcode: '',
        args: '',
        raw: '',
      });
      continue;
    }
    if (buf.length === 0) bufStartLine = li;
    buf.push(ln);
  }
  flushBuf();
  // Re-number
  rows.forEach((r, i) => { r.seq = i; });
  return rows;

  function flushBuf() {
    if (buf.length === 0) return;
    const chunk = buf.join('\n');
    buf.length = 0;
    bufStartLine = -1;
    // Split into statements on ';'. Empty stmts between semis are dropped.
    const parts = chunk.split(';');
    for (const part of parts) {
      const s = part.trim();
      if (s === '') continue;
      const m = s.match(/^([A-Za-z]{2})(?:\s*,(.*))?$/s);
      if (m) {
        rows.push({
          id: state._stmtIdCounter++,
          seq: rows.length,
          kind: 'stmt',
          opcode: m[1].toLowerCase(),
          args: (m[2] || '').trim(),
          raw: s,
        });
      } else {
        // Unparseable → keep the raw text so the user can fix it in-place.
        rows.push({
          id: state._stmtIdCounter++,
          seq: rows.length,
          kind: 'stmt',
          opcode: '??',
          args: s,
          raw: s,
        });
      }
    }
  }
}

function serializeDrawlang(rows) {
  const out = [];
  for (const r of rows) {
    if (r.kind === 'comment') {
      out.push('# ' + r.args);
    } else if (r.kind === 'blank') {
      out.push('');
    } else {
      // Statement row.
      const op = (r.opcode || '').trim();
      const args = (r.args || '').trim();
      if (!op) continue;
      out.push(args ? `${op},${args};` : `${op};`);
    }
  }
  return out.join('\n');
}

// ---------- Frame list ----------

async function reloadFrameList() {
  const data = await apiGet('/api/frames');
  state.frames = data.frames || [];
  renderFrameList();
}
function renderFrameList() {
  const list = document.getElementById('frame-list');
  if (!state.frames.length) {
    list.innerHTML = `<div style="padding:12px;color:#7A7974;font-size:12px">No frames yet.</div>`;
    return;
  }
  list.innerHTML = state.frames.map(f => {
    const active = f.id === state.frameId ? ' active' : '';
    const dirty = (f.id === state.frameId && isDirty()) ? ' dirty' : '';
    const label = f.name && f.name !== f.id ? `${f.id} <span style="opacity:0.7">— ${escapeHtml(f.name)}</span>` : f.id;
    const count = f.field_count != null ? ` <span style="opacity:0.6">(${f.field_count})</span>` : '';
    return `<div class="frame-item${active}${dirty}" data-id="${escapeAttr(f.id)}">${label}${count}</div>`;
  }).join('');
  for (const el of list.querySelectorAll('.frame-item')) {
    el.addEventListener('click', () => onSelectFrame(el.dataset.id));
  }
}

// ---------- Load a frame ----------

async function onSelectFrame(fid) {
  if (state.frameId === fid) return;
  if (isDirty() && !confirm('Discard unsaved changes to this frame?')) return;
  state.frameId = fid;
  document.getElementById('empty-pane').style.display = 'none';
  document.getElementById('frame-body').style.display = 'flex';
  document.getElementById('frame-body').style.flexDirection = 'column';
  document.getElementById('delete-frame-btn').disabled = false;
  setStatus('Loading frame…');
  try {
    const data = await apiGet(`/api/frames/${encodeURIComponent(fid)}/raw`);
    state.loaded = {
      id: data.id,
      name: data.name || data.id,
      drawlang: data.drawlang || '',
      fields: Array.isArray(data.fields) ? data.fields : [],
    };
    state.edits = deepCopy(state.loaded);
    state.tokensDetected = [];
    state.statements = parseDrawlang(state.edits.drawlang);
    state.cursorId = state.statements.length ? state.statements[0].id : null;
    renderAll();
    renderFrameList();
    setStatus('');
  } catch (e) {
    setStatus('Load failed: ' + e.message, 'error');
  }
}

// ---------- Dirty tracking ----------

function isDirty() {
  if (!state.loaded || !state.edits) return false;
  if (state.loaded.name !== state.edits.name) return true;
  if (state.loaded.drawlang !== state.edits.drawlang) return true;
  return JSON.stringify(state.loaded.fields) !== JSON.stringify(state.edits.fields);
}
function refreshSaveBtn() {
  const dirty = isDirty();
  document.getElementById('save-btn').disabled = !dirty;
  document.getElementById('revert-btn').disabled = !dirty;
  renderFrameList(); // for dirty marker
}

// ---------- Render editor ----------

function renderAll() {
  document.getElementById('frame-id').value = state.edits.id || '';
  document.getElementById('frame-name').value = state.edits.name || '';
  document.getElementById('drawlang-input').value = state.edits.drawlang || '';
  renderStatementList();
  renderFieldsTab();
  refreshSaveBtn();
  if (state.activeTab === 'stmts') schedulePreview();
}

// ---------- Statement panel ----------

function renderStatementList() {
  const el = document.getElementById('stmt-list');
  if (!state.statements.length) {
    el.innerHTML = `<div style="color:#7A7974;padding:8px">Empty. Type below and press Insert, or paste bulk drawlang in the <b>Raw</b> tab.</div>`;
    return;
  }
  el.innerHTML = state.statements.map((s) => {
    const cur = state.cursorId === s.id ? ' cursor' : '';
    if (s.kind === 'comment') {
      return `<div class="stmt-row comment${cur}" data-id="${s.id}" data-seq="${s.seq}" tabindex="0" draggable="true">
        <span class="stmt-grip" title="Drag to reorder">⋮</span>
        <span class="stmt-seq">${s.seq + 1}</span>
        <span class="stmt-op">#</span>
        <span class="stmt-args" data-edit-args="${s.id}" title="Click to edit comment">${escapeHtml(s.args)}</span>
        <span class="stmt-actions">
          <button data-insert-before="${s.id}" title="Insert line above">+↑</button>
          <button data-insert-after="${s.id}" title="Insert line below">+↓</button>
          <button class="stmt-del" data-del="${s.id}" title="Delete (Del)">✕</button>
        </span>
      </div>`;
    }
    if (s.kind === 'blank') {
      return `<div class="stmt-row comment${cur}" data-id="${s.id}" data-seq="${s.seq}" tabindex="0" draggable="true">
        <span class="stmt-grip" title="Drag to reorder">⋮</span>
        <span class="stmt-seq">${s.seq + 1}</span>
        <span class="stmt-op"></span>
        <span class="stmt-args" style="opacity:0.5">(blank line)</span>
        <span class="stmt-actions">
          <button data-insert-before="${s.id}" title="Insert line above">+↑</button>
          <button data-insert-after="${s.id}" title="Insert line below">+↓</button>
          <button class="stmt-del" data-del="${s.id}" title="Delete (Del)">✕</button>
        </span>
      </div>`;
    }
    return `<div class="stmt-row${cur}" data-id="${s.id}" data-seq="${s.seq}" tabindex="0" draggable="true">
      <span class="stmt-grip" title="Drag to reorder">⋮</span>
      <span class="stmt-seq">${s.seq + 1}</span>
      <span class="stmt-op" data-edit-op="${s.id}" title="Click to edit opcode">${escapeHtml(s.opcode)}</span>
      <span class="stmt-args" data-edit-args="${s.id}" title="Click to edit args">${escapeHtml(s.args)}</span>
      <span class="stmt-actions">
        <button data-insert-before="${s.id}" title="Insert line above (⇧Enter)">+↑</button>
        <button data-insert-after="${s.id}" title="Insert line below (Enter)">+↓</button>
        <button class="stmt-del" data-del="${s.id}" title="Delete (Del)">✕</button>
      </span>
    </div>`;
  }).join('');

  // Row click → cursor
  el.querySelectorAll('.stmt-row').forEach((row) => {
    row.addEventListener('click', (e) => {
      // Don't hijack clicks on inline editors or action buttons.
      if (e.target.closest('button, [contenteditable="true"]')) return;
      state.cursorId = parseInt(row.dataset.id);
      renderStatementList();
    });
    row.addEventListener('focus', () => {
      state.cursorId = parseInt(row.dataset.id);
    });
    row.addEventListener('keydown', onRowKeydown);
  });

  // Inline edit for opcode + args
  el.querySelectorAll('[data-edit-op], [data-edit-args]').forEach((cell) => {
    cell.addEventListener('click', (e) => {
      e.stopPropagation();
      startInlineEdit(cell);
    });
  });

  // Buttons
  el.querySelectorAll('[data-del]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteRow(parseInt(btn.dataset.del));
    });
  });
  el.querySelectorAll('[data-insert-before]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      insertBefore(parseInt(btn.dataset.insertBefore));
    });
  });
  el.querySelectorAll('[data-insert-after]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      insertAfter(parseInt(btn.dataset.insertAfter));
    });
  });

  wireStatementDrag(el);
}

function startInlineEdit(cell) {
  const id = parseInt(cell.dataset.editOp || cell.dataset.editArgs);
  const isOp = !!cell.dataset.editOp;
  const stmt = state.statements.find((s) => s.id === id);
  if (!stmt) return;
  state.cursorId = id;
  cell.contentEditable = 'true';
  cell.focus();
  // Select-all
  const range = document.createRange();
  range.selectNodeContents(cell);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);

  const finish = (commit) => {
    cell.contentEditable = 'false';
    cell.removeEventListener('blur', onBlur);
    cell.removeEventListener('keydown', onKey);
    if (!commit) {
      renderStatementList();
      return;
    }
    const val = cell.textContent.trim();
    if (isOp) {
      // Empty opcode → treat as blank line marker; two-letter opcode required.
      if (val === '') { stmt.opcode = ''; }
      else if (/^[A-Za-z]{2}$/.test(val)) { stmt.opcode = val.toLowerCase(); }
      else { setStatus('Opcode must be two letters.', 'error'); setTimeout(()=>setStatus(''), 2000); }
    } else {
      stmt.args = val;
    }
    commitStatementsChange();
  };
  const onBlur = () => finish(true);
  const onKey = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    else if (e.key === 'Tab') {
      e.preventDefault();
      finish(true);
      // Move to next cell.
      const rows = Array.from(document.querySelectorAll('.stmt-row'));
      const idx = rows.findIndex((r) => parseInt(r.dataset.id) === id);
      if (idx >= 0) {
        const nextRow = e.shiftKey ? rows[idx - 1] : rows[idx + 1];
        if (nextRow) {
          const target = nextRow.querySelector(isOp ? '[data-edit-op]' : '[data-edit-args]');
          if (target) startInlineEdit(target);
        }
      }
    }
  };
  cell.addEventListener('blur', onBlur);
  cell.addEventListener('keydown', onKey);
}

function onRowKeydown(e) {
  const rows = state.statements;
  const idx = rows.findIndex((s) => s.id === state.cursorId);
  if (idx < 0) return;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    const next = rows[Math.min(idx + 1, rows.length - 1)];
    if (next) { state.cursorId = next.id; renderStatementList(); focusCursor(); }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    const prev = rows[Math.max(idx - 1, 0)];
    if (prev) { state.cursorId = prev.id; renderStatementList(); focusCursor(); }
  } else if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    insertAfter(state.cursorId);
  } else if (e.key === 'Enter' && e.shiftKey) {
    e.preventDefault();
    insertBefore(state.cursorId);
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault();
    deleteRow(state.cursorId);
  } else if (e.key === 'F2' || e.key === ' ') {
    e.preventDefault();
    const row = document.querySelector(`.stmt-row[data-id="${state.cursorId}"]`);
    const cell = row && row.querySelector('[data-edit-args]');
    if (cell) startInlineEdit(cell);
  }
}
function focusCursor() {
  const row = document.querySelector(`.stmt-row[data-id="${state.cursorId}"]`);
  if (row) row.focus();
}

function insertAfter(afterId) {
  const idx = state.statements.findIndex((s) => s.id === afterId);
  const at = idx < 0 ? state.statements.length : idx + 1;
  _insertNew(at);
}
function insertBefore(beforeId) {
  const idx = state.statements.findIndex((s) => s.id === beforeId);
  const at = idx < 0 ? 0 : idx;
  _insertNew(at);
}
function _insertNew(at) {
  const row = {
    id: state._stmtIdCounter++,
    seq: 0, kind: 'stmt',
    opcode: 'mr', args: '0,0',
    raw: 'mr,0,0',
  };
  state.statements.splice(at, 0, row);
  state.statements.forEach((s, i) => { s.seq = i; });
  state.cursorId = row.id;
  commitStatementsChange();
  // Auto-start inline edit on args of the new row so typing is immediate.
  requestAnimationFrame(() => {
    const cell = document.querySelector(`[data-edit-args="${row.id}"]`);
    if (cell) startInlineEdit(cell);
  });
}
function deleteRow(id) {
  const idx = state.statements.findIndex((s) => s.id === id);
  if (idx < 0) return;
  state.statements.splice(idx, 1);
  state.statements.forEach((s, i) => { s.seq = i; });
  if (state.cursorId === id) {
    const next = state.statements[Math.min(idx, state.statements.length - 1)];
    state.cursorId = next ? next.id : null;
  }
  commitStatementsChange();
}

// Every statement-level mutation funnels through here so drawlang, dirty
// flag, fields tab (for token detection), and preview stay in sync.
function commitStatementsChange() {
  state.edits.drawlang = serializeDrawlang(state.statements);
  document.getElementById('drawlang-input').value = state.edits.drawlang;
  renderStatementList();
  if (state.activeTab === 'fields') renderFieldsTab();
  refreshSaveBtn();
  schedulePreview();
}

// ---------- Drag-to-reorder ----------

function wireStatementDrag(container) {
  container.querySelectorAll('.stmt-row').forEach((row) => {
    row.addEventListener('dragstart', (e) => {
      state._dragId = parseInt(row.dataset.id);
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', String(state._dragId)); } catch(_) {}
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('dragging');
      container.querySelectorAll('.stmt-row').forEach((r) => {
        r.classList.remove('drag-over-top', 'drag-over-bot');
      });
      state._dragId = null;
    });
    row.addEventListener('dragover', (e) => {
      if (state._dragId == null) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = row.getBoundingClientRect();
      const above = (e.clientY - rect.top) < rect.height / 2;
      row.classList.toggle('drag-over-top', above);
      row.classList.toggle('drag-over-bot', !above);
    });
    row.addEventListener('dragleave', () => {
      row.classList.remove('drag-over-top', 'drag-over-bot');
    });
    row.addEventListener('drop', (e) => {
      if (state._dragId == null) return;
      e.preventDefault();
      const targetId = parseInt(row.dataset.id);
      const rect = row.getBoundingClientRect();
      const above = (e.clientY - rect.top) < rect.height / 2;
      row.classList.remove('drag-over-top', 'drag-over-bot');
      const draggedId = state._dragId;
      state._dragId = null;
      if (draggedId === targetId) return;
      // Reorder in state.statements
      const draggedIdx = state.statements.findIndex((s) => s.id === draggedId);
      if (draggedIdx < 0) return;
      const [moved] = state.statements.splice(draggedIdx, 1);
      const targetIdx = state.statements.findIndex((s) => s.id === targetId);
      if (targetIdx < 0) return;
      const insertAt = above ? targetIdx : targetIdx + 1;
      state.statements.splice(insertAt, 0, moved);
      state.statements.forEach((s, i) => { s.seq = i; });
      state.cursorId = moved.id;
      commitStatementsChange();
    });
  });
}

// ---------- Live preview ----------

function schedulePreview() {
  clearTimeout(state._previewTimer);
  state._previewTimer = setTimeout(renderStmtPreview, 350);
}

async function renderStmtPreview() {
  const el = document.getElementById('stmt-preview');
  if (!el) return;
  // Build a preview program: replace {{token}} with token name so unresolved
  // placeholders draw something visible; also strip comment/blank rows on
  // the client (server strips comments too but explicit is safer).
  const prog = serializeDrawlang(state.statements)
    .split(/\r?\n/)
    .filter((ln) => !ln.trim().startsWith('#') && ln.trim() !== '')
    .join('\n')
    // Replace {{name}} tokens with their default value (from Fields) or the
    // token name so preview isn't blocked by literal {{}} which the renderer
    // may not tolerate.
    .replace(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, (m, name) => {
      const f = (state.edits.fields || []).find((x) => x.name === name);
      return (f && f.default != null && String(f.default) !== '') ? String(f.default) : name;
    });
  if (!prog.trim()) {
    el.innerHTML = '<div class="preview-empty">Add statements to see a live preview.</div>';
    return;
  }
  try {
    const data = await apiPost('/render', { program: prog, backend: 'svg' });
    if (data.ok) {
      el.innerHTML = data.output || '<div class="preview-empty">(empty render)</div>';
    } else {
      const kind = escapeHtml(data.error_kind || 'Error');
      const msg = escapeHtml(data.error || '');
      const at = data.statement_index != null ? ` (statement #${data.statement_index + 1})` : '';
      el.innerHTML = `<div class="preview-error"><b>${kind}${at}:</b> ${msg}</div>`;
    }
  } catch (e) {
    el.innerHTML = `<div class="preview-error">Render call failed: ${escapeHtml(e.message)}</div>`;
  }
}

// ---------- Fields tab ----------

function renderFieldsTab() {
  const tbody = document.getElementById('fields-tbody');
  const empty = document.getElementById('fields-empty');
  const fields = state.edits.fields || [];
  if (!fields.length) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  const tokensInDrawlang = extractTokens(state.edits.drawlang || '');
  const inDl = new Set(tokensInDrawlang);
  tbody.innerHTML = fields.map((f, i) => {
    const tag = inDl.has(f.name) ? '<span class="tag declared">used</span>' : '<span class="tag orphan">unused</span>';
    return `<tr data-idx="${i}">
      <td class="col-name"><input class="f-name" value="${escapeAttr(f.name || '')}"></td>
      <td class="col-default"><input class="f-default" value="${escapeAttr(f.default || '')}"></td>
      <td class="col-label"><input class="f-label" value="${escapeAttr(f.label || f.description || '')}"></td>
      <td class="col-tag">${tag}</td>
      <td class="col-del"><button class="del-btn" title="Remove field">×</button></td>
    </tr>`;
  }).join('');
  for (const tr of tbody.querySelectorAll('tr')) {
    const idx = Number(tr.dataset.idx);
    tr.querySelector('.f-name').addEventListener('input', e => updateField(idx, 'name', e.target.value));
    tr.querySelector('.f-default').addEventListener('input', e => updateField(idx, 'default', e.target.value));
    tr.querySelector('.f-label').addEventListener('input', e => updateField(idx, 'label', e.target.value));
    tr.querySelector('.del-btn').addEventListener('click', () => removeField(idx));
  }
}

function updateField(idx, key, val) {
  state.edits.fields[idx][key] = val;
  refreshSaveBtn();
}
function removeField(idx) {
  state.edits.fields.splice(idx, 1);
  renderFieldsTab();
  refreshSaveBtn();
}

function addFieldRow(name = '', defaultValue = '') {
  const maxIdx = state.edits.fields.reduce((m,f) =>
    Math.max(m, Number.isFinite(f.line_index) ? f.line_index : -1), -1);
  state.edits.fields.push({
    name, default: defaultValue, label: '',
    editable: true, line_index: maxIdx + 1,
  });
}

async function scanTokens() {
  setFieldsError('');
  const declaredNames = new Set(state.edits.fields.map(f => f.name).filter(Boolean));
  const tokens = extractTokens(state.edits.drawlang || '');
  const undeclared = tokens.filter(t => !declaredNames.has(t));
  if (!undeclared.length) {
    setStatus(`No new tokens (${tokens.length} total in drawlang).`, 'success');
    setTimeout(() => setStatus(''), 2500);
    renderFieldsTab();
    return;
  }
  for (const t of undeclared) addFieldRow(t, '');
  renderFieldsTab();
  refreshSaveBtn();
  setStatus(`Added ${undeclared.length} new field row${undeclared.length===1?'':'s'}.`, 'success');
  setTimeout(() => setStatus(''), 2500);
}

function extractTokens(prog) {
  const seen = new Set();
  const out = [];
  const re = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;
  let m;
  while ((m = re.exec(prog)) !== null) {
    if (!seen.has(m[1])) { seen.add(m[1]); out.push(m[1]); }
  }
  return out;
}

// ---------- Insert box (cmd-input) ----------

function onInsertBox() {
  const inp = document.getElementById('cmd-input');
  const raw = (inp.value || '').trim();
  if (!raw) return;
  // Support "opcode,args" and multi-statement "op1,a;op2,b;"
  if (raw.includes(';')) {
    const rows = parseDrawlang(raw);
    if (!rows.length) return;
    // Insert after cursor (or at end)
    const cursorIdx = state.cursorId != null
      ? state.statements.findIndex((s) => s.id === state.cursorId)
      : -1;
    let at = cursorIdx < 0 ? state.statements.length : cursorIdx + 1;
    for (const r of rows) {
      state.statements.splice(at, 0, r);
      at += 1;
    }
    state.statements.forEach((s, i) => { s.seq = i; });
    state.cursorId = state.statements[at - 1].id;
    inp.value = '';
    commitStatementsChange();
    return;
  }
  const m = raw.match(/^([A-Za-z]{2})(?:,(.*))?$/s);
  if (!m) {
    setStatus('Format: opcode,args (e.g. mr,20,0)', 'error');
    setTimeout(()=>setStatus(''), 2500);
    return;
  }
  const cursorIdx = state.cursorId != null
    ? state.statements.findIndex((s) => s.id === state.cursorId)
    : -1;
  const at = cursorIdx < 0 ? state.statements.length : cursorIdx + 1;
  const row = {
    id: state._stmtIdCounter++,
    seq: 0, kind: 'stmt',
    opcode: m[1].toLowerCase(),
    args: (m[2] || '').trim(),
    raw,
  };
  state.statements.splice(at, 0, row);
  state.statements.forEach((s, i) => { s.seq = i; });
  state.cursorId = row.id;
  inp.value = '';
  commitStatementsChange();
}

// ---------- Tabs ----------

function setActiveTab(name) {
  // On switching AWAY from Raw, reparse if the textarea changed.
  if (state.activeTab === 'raw' && name !== 'raw') {
    const ta = document.getElementById('drawlang-input').value;
    if (ta !== state.edits.drawlang) {
      state.edits.drawlang = ta;
      state.statements = parseDrawlang(ta);
      state.cursorId = state.statements.length ? state.statements[0].id : null;
      refreshSaveBtn();
    }
  }
  state.activeTab = name;
  for (const t of document.querySelectorAll('.tab')) {
    t.classList.toggle('active', t.dataset.tab === name);
  }
  for (const c of document.querySelectorAll('.tab-content')) {
    c.classList.toggle('active', c.dataset.tab === name);
  }
  if (name === 'stmts') { renderStatementList(); schedulePreview(); }
  if (name === 'raw') {
    document.getElementById('drawlang-input').value = state.edits.drawlang || '';
  }
  if (name === 'fields') renderFieldsTab();
}

// ---------- Save / new / delete ----------

async function saveFrame() {
  if (!state.frameId) return;
  const names = new Set();
  for (const f of state.edits.fields) {
    const nm = (f.name || '').trim();
    if (!nm) { setFieldsError('Every field needs a name.'); setActiveTab('fields'); return; }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(nm)) {
      setFieldsError(`Field name "${nm}" is invalid (letters, digits, underscore; must start with letter or _).`);
      setActiveTab('fields'); return;
    }
    if (names.has(nm)) { setFieldsError(`Duplicate field name "${nm}".`); setActiveTab('fields'); return; }
    names.add(nm);
    f.name = nm;
    if (!('editable' in f)) f.editable = true;
    if (!Number.isFinite(f.line_index)) {
      const maxIdx = state.edits.fields.reduce((m,x)=>Math.max(m, Number.isFinite(x.line_index)?x.line_index:-1), -1);
      f.line_index = maxIdx + 1;
    }
  }
  setFieldsError('');
  setStatus('Saving…');
  try {
    // If the user was in Raw tab, pick up their unsaved textarea text.
    if (state.activeTab === 'raw') {
      state.edits.drawlang = document.getElementById('drawlang-input').value;
    }
    const body = {
      name: state.edits.name,
      drawlang: state.edits.drawlang,
      fields: state.edits.fields,
    };
    await apiPatch(`/api/frames/${encodeURIComponent(state.frameId)}`, body);
    state.loaded = deepCopy(state.edits);
    setStatus('Saved.', 'success');
    setTimeout(() => setStatus(''), 2000);
    await reloadFrameList();
    refreshSaveBtn();
  } catch (e) {
    setStatus('Save failed: ' + e.message, 'error');
  }
}

function revert() {
  if (!state.loaded) return;
  state.edits = deepCopy(state.loaded);
  state.statements = parseDrawlang(state.edits.drawlang);
  state.cursorId = state.statements.length ? state.statements[0].id : null;
  renderAll();
  setStatus('Reverted.', 'success');
  setTimeout(() => setStatus(''), 1500);
}

async function newFrame() {
  const id = window.prompt('New frame id (letters, digits, hyphen, underscore):');
  if (!id) return;
  if (!/^[A-Za-z0-9_-]+$/.test(id)) {
    alert('Invalid id.'); return;
  }
  const body = {
    id, name: id,
    drawlang: '# New frame — add statements below.\n',
    fields: [],
  };
  try {
    setStatus('Creating…');
    await apiPost('/api/frames', body);
    setStatus('Created.', 'success');
    setTimeout(() => setStatus(''), 1500);
    await reloadFrameList();
    await onSelectFrame(id);
  } catch (e) {
    setStatus('Create failed: ' + e.message, 'error');
  }
}

async function deleteFrame() {
  if (!state.frameId) return;
  if (!confirm(`Delete frame "${state.frameId}"? Canvases referencing it keep their frame_id (broken until re-created).`)) return;
  try {
    setStatus('Deleting…');
    await apiDelete(`/api/frames/${encodeURIComponent(state.frameId)}`);
    setStatus('Deleted.', 'success');
    setTimeout(() => setStatus(''), 1500);
    state.frameId = null;
    state.loaded = null;
    state.edits = null;
    state.statements = [];
    document.getElementById('empty-pane').style.display = 'flex';
    document.getElementById('frame-body').style.display = 'none';
    document.getElementById('delete-frame-btn').disabled = true;
    await reloadFrameList();
  } catch (e) {
    setStatus('Delete failed: ' + e.message, 'error');
  }
}

// ---------- Utilities ----------

function deepCopy(x) { return JSON.parse(JSON.stringify(x)); }
function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, m =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function escapeAttr(s) { return escapeHtml(s); }

// ---------- Wire up ----------

document.addEventListener('DOMContentLoaded', async () => {
  for (const t of document.querySelectorAll('.tab')) {
    t.addEventListener('click', () => setActiveTab(t.dataset.tab));
  }
  document.getElementById('frame-name').addEventListener('input', e => {
    state.edits.name = e.target.value; refreshSaveBtn();
  });
  document.getElementById('drawlang-input').addEventListener('input', e => {
    // Raw-tab edits: update state.edits.drawlang immediately so isDirty()
    // fires. Statements list is re-parsed on tab switch.
    state.edits.drawlang = e.target.value;
    refreshSaveBtn();
  });
  document.getElementById('save-btn').addEventListener('click', saveFrame);
  document.getElementById('revert-btn').addEventListener('click', revert);
  document.getElementById('new-frame-btn').addEventListener('click', newFrame);
  document.getElementById('delete-frame-btn').addEventListener('click', deleteFrame);
  document.getElementById('scan-btn').addEventListener('click', scanTokens);
  document.getElementById('add-field-btn').addEventListener('click', () => {
    addFieldRow('', '');
    renderFieldsTab();
    refreshSaveBtn();
    setActiveTab('fields');
  });
  document.getElementById('cmd-add').addEventListener('click', onInsertBox);
  document.getElementById('cmd-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); onInsertBox(); }
  });

  try {
    await reloadFrameList();
    if (state.frames.length) {
      await onSelectFrame(state.frames[0].id);
    } else {
      setStatus('No frames yet — create one to begin.');
    }
  } catch (e) {
    setStatus('Failed to list frames: ' + e.message, 'error');
  }
});
