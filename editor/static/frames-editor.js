// v0.7.6 Frame Editor — DrawLang / Fields / Preview tabs.
// Everything goes through the JSON API (POST/PATCH/DELETE /api/frames/...).
// No prompt() dialogs, no direct DB writes, no localStorage.

const API = ''; // same-origin

const state = {
  frames: [],           // [{id, name, ...}] from /api/frames
  frameId: null,        // currently selected frame id
  loaded: null,         // last-fetched frame from API (name/drawlang/fields)
  edits: null,          // in-memory edits { name, drawlang, fields }
  activeTab: 'drawlang',
  tokensDetected: [],   // last scan result
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
    // /api/frames/{id}/raw returns the true stored shape: all fields (editable
    // and non-editable), raw drawlang, no value substitution.
    const data = await apiGet(`/api/frames/${encodeURIComponent(fid)}/raw`);
    state.loaded = {
      id: data.id,
      name: data.name || data.id,
      drawlang: data.drawlang || '',
      fields: Array.isArray(data.fields) ? data.fields : [],
    };
    state.edits = deepCopy(state.loaded);
    state.tokensDetected = [];
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
  renderFieldsTab();
  refreshSaveBtn();
  if (state.activeTab === 'preview') renderPreview();
}

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
  // Don't re-render the whole table on every keystroke — it would blur inputs.
}
function removeField(idx) {
  state.edits.fields.splice(idx, 1);
  renderFieldsTab();
  refreshSaveBtn();
}

function addFieldRow(name = '', defaultValue = '') {
  // Determine next line_index for backward-compat with /api/frames/{id}/render.
  const maxIdx = state.edits.fields.reduce((m,f) =>
    Math.max(m, Number.isFinite(f.line_index) ? f.line_index : -1), -1);
  state.edits.fields.push({
    name, default: defaultValue, label: '',
    editable: true, line_index: maxIdx + 1,
  });
}

// ---------- Scan drawlang for tokens ----------

async function scanTokens() {
  // If the frame is saved with the current drawlang, we can call the API.
  // If the user has unsaved edits, we scan client-side to avoid a
  // "save-before-scan" wall.
  setFieldsError('');
  const declaredNames = new Set(state.edits.fields.map(f => f.name).filter(Boolean));
  const drawlangDirty = state.loaded.drawlang !== state.edits.drawlang;
  let tokens;
  if (drawlangDirty || !state.frameId) {
    tokens = extractTokens(state.edits.drawlang || '');
  } else {
    try {
      const data = await apiGet(`/api/frames/${encodeURIComponent(state.frameId)}/tokens`);
      tokens = data.tokens || [];
    } catch (e) {
      setFieldsError('Scan failed: ' + e.message);
      return;
    }
  }
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

// Client-side token extraction, mirrors backend regex.
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

// ---------- Preview ----------

async function renderPreview() {
  const el = document.getElementById('preview');
  if (!state.frameId) {
    el.innerHTML = '<div class="preview-empty">Select a frame.</div>';
    return;
  }
  if (isDirty()) {
    el.innerHTML = '<div class="preview-empty">Save the frame to render a preview.</div>';
    return;
  }
  el.innerHTML = '<div class="preview-empty">Rendering…</div>';
  try {
    const data = await apiPost(`/api/frames/${encodeURIComponent(state.frameId)}/render`, {values: {}});
    el.innerHTML = data.output || '<div class="preview-empty">(empty render)</div>';
    el.className = ''; // remove any 'preview-empty' class
  } catch (e) {
    el.innerHTML = `<div class="error">Render failed: ${escapeHtml(e.message)}</div>`;
  }
}

// ---------- Tabs ----------

function setActiveTab(name) {
  state.activeTab = name;
  for (const t of document.querySelectorAll('.tab')) {
    t.classList.toggle('active', t.dataset.tab === name);
  }
  for (const c of document.querySelectorAll('.tab-content')) {
    c.classList.toggle('active', c.dataset.tab === name);
  }
  if (name === 'preview') renderPreview();
  if (name === 'fields') renderFieldsTab();
}

// ---------- Save / new / delete ----------

async function saveFrame() {
  if (!state.frameId) return;
  // Validate field names before submitting.
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
    const body = {
      name: state.edits.name,
      drawlang: state.edits.drawlang,
      fields: state.edits.fields,
    };
    const data = await apiPatch(`/api/frames/${encodeURIComponent(state.frameId)}`, body);
    state.loaded = deepCopy(state.edits);
    setStatus('Saved.', 'success');
    setTimeout(() => setStatus(''), 2000);
    await reloadFrameList();
    refreshSaveBtn();
    if (state.activeTab === 'preview') renderPreview();
  } catch (e) {
    setStatus('Save failed: ' + e.message, 'error');
  }
}

function revert() {
  if (!state.loaded) return;
  state.edits = deepCopy(state.loaded);
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
    drawlang: '# New frame — edit drawlang here.\n',
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
    state.edits.drawlang = e.target.value; refreshSaveBtn();
    if (state.activeTab === 'fields') renderFieldsTab();
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
