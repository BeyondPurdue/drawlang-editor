const API = ''; // same-origin
const state = {
  frameId: null,
  fields: [],       // [{name, description, x, y, value}]
  values: {},       // {name: current_value}
  svg: null,
  activeField: null,
};

async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function setStatus(msg, cls='') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + cls;
}
function setError(msg) {
  document.getElementById('error').innerHTML = msg ? `<div class="error">${msg}</div>` : '';
}

async function loadFrameList() {
  const {frames} = await apiGet('/api/frames');
  const sel = document.getElementById('frame-select');
  sel.innerHTML = frames.map(f => `<option value="${f.id}">${f.id} (${f.field_count} fields)</option>`).join('');
  sel.addEventListener('change', () => loadFrame(sel.value));
  if (frames.length) return frames[0].id;
  return null;
}

async function loadFrame(frameId) {
  state.frameId = frameId;
  setStatus('Loading frame…');
  const data = await apiGet('/api/frames/' + frameId);
  state.fields = data.fields;
  state.values = {};
  for (const f of data.fields) state.values[f.name] = f.value || '';
  renderSidebar();
  await refreshPreview();
  setStatus('Ready · ' + data.fields.length + ' editable fields');
}

function renderSidebar() {
  const html = state.fields.map(f => `
    <div class="field" data-field="${f.name}">
      <label>${f.description || f.name}</label>
      <input type="text" data-name="${f.name}" value="${escapeAttr(state.values[f.name])}" placeholder="${escapeAttr(f.description)}">
    </div>
  `).join('');
  document.getElementById('fields').innerHTML = html;
  document.querySelectorAll('.field input').forEach(inp => {
    inp.addEventListener('input', onInputChange);
    inp.addEventListener('focus', () => highlightField(inp.dataset.name));
    inp.addEventListener('blur', () => highlightField(null));
  });
}

function escapeAttr(s) { return String(s ?? '').replace(/"/g, '&quot;'); }

let saveTimer = null;
function onInputChange(e) {
  const name = e.target.dataset.name;
  const oldVal = state.values[name];
  const newVal = e.target.value;
  state.values[name] = newVal;
  e.target.classList.toggle('dirty', newVal !== oldVal);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(refreshPreview, 300);
}

async function refreshPreview() {
  setStatus('Rendering…');
  setError('');
  document.getElementById('preview').classList.add('saving');
  try {
    const data = await apiPost(`/api/frames/${state.frameId}/render`, { values: state.values });
    if (!data.ok) {
      setError('Render error: ' + data.error);
      setStatus('Error', 'error');
      return;
    }
    document.getElementById('preview').innerHTML = data.output;
    state.svg = data.output;
    attachHotspots();
    setStatus('Rendered · ' + Object.values(state.values).filter(v => v).length + ' fields filled');
    document.querySelectorAll('.field input.dirty').forEach(i => i.classList.remove('dirty'));
  } catch (e) {
    setError('API error: ' + e.message);
    setStatus('Error', 'error');
  } finally {
    document.getElementById('preview').classList.remove('saving');
  }
}

function attachHotspots() {
  // Overlay a rectangle on each field position so users can click on the frame to edit.
  const svg = document.querySelector('#preview svg');
  if (!svg) return;
  const viewBox = svg.getAttribute('viewBox').split(' ').map(Number);
  // ES680 coord system: origin at lower-left, y-up. SVG viewBox in "canonical" units matches drawlang units.
  // Our svg output already flips Y. Hotspot: draw small rect at each field's (x, y) — need to convert.

  // The renderer emits svg with viewBox="-44.1 -926.1 1340.2 970.2" (from earlier probe).
  // Content coords in drawlang: (0,0) to (1223, 679). In SVG output: X unchanged, Y flipped and translated.
  // Empirically viewBox y range is [-926, 44]. So SVG y = -drawlang_y (approximately).
  // Add hotspot rects to a <g> layer.

  const NS = 'http://www.w3.org/2000/svg';
  const layer = document.createElementNS(NS, 'g');
  layer.setAttribute('id', 'hotspot-layer');

  state.fields.forEach(f => {
    const w = Math.max(60, (f.name === 'plant_name' || f.name === 'customer_name' || f.name === 'function_desc') ? 260 : 80);
    const h = 12;
    // Position: x, y in drawlang. SVG y is flipped -> use -y - h/2. Field origin is text baseline.
    const rect = document.createElementNS(NS, 'rect');
    rect.setAttribute('x', f.x - 2);
    rect.setAttribute('y', -f.y - h + 2);  // above baseline
    rect.setAttribute('width', w);
    rect.setAttribute('height', h);
    rect.setAttribute('class', 'hotspot');
    rect.setAttribute('data-field', f.name);
    rect.addEventListener('click', () => {
      const inp = document.querySelector(`input[data-name="${f.name}"]`);
      if (inp) { inp.focus(); inp.select(); }
    });
    layer.appendChild(rect);
  });
  svg.appendChild(layer);
}

function highlightField(name) {
  document.querySelectorAll('.hotspot').forEach(r => {
    r.classList.toggle('active', r.dataset.field === name);
  });
}

document.getElementById('reset-btn').addEventListener('click', () => {
  for (const k of Object.keys(state.values)) state.values[k] = '';
  document.querySelectorAll('.field input').forEach(i => { i.value = ''; });
  refreshPreview();
});

document.getElementById('export-svg').addEventListener('click', () => {
  if (!state.svg) return;
  const blob = new Blob([state.svg], {type: 'image/svg+xml'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `${state.frameId}.svg`; a.click();
  URL.revokeObjectURL(url);
});

(async function main() {
  try {
    const first = await loadFrameList();
    if (first) await loadFrame(first);
    else setStatus('No frames available', 'error');
  } catch (e) {
    setStatus('Init error: ' + e.message, 'error');
  }
})();
