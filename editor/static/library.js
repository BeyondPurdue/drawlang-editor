const $ = (id) => document.getElementById(id);
const state = { items: [], categories: [], currentCategory: null, currentItem: null };

async function api(url, opts={}) {
  const res = await fetch(url, { headers: {"Content-Type":"application/json"}, ...opts });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

async function refresh() {
  const { items } = await api("/api/library");
  state.items = items;
  const cats = [...new Set(items.map(i => i.category))].sort();
  state.categories = cats;
  renderCats();
  renderItems();
}

function renderCats() {
  const el = $("cats-list");
  const all = `<div class="cat${!state.currentCategory ? " active" : ""}" data-cat="">All (${state.items.length})</div>`;
  const list = state.categories.map(c => {
    const n = state.items.filter(i => i.category === c).length;
    return `<div class="cat${state.currentCategory === c ? " active" : ""}" data-cat="${c}">${c} (${n})</div>`;
  }).join("");
  el.innerHTML = all + list;
  el.querySelectorAll(".cat").forEach(d => {
    d.addEventListener("click", () => {
      state.currentCategory = d.dataset.cat || null;
      renderCats(); renderItems();
    });
  });
}

function renderItems() {
  const filtered = state.currentCategory
    ? state.items.filter(i => i.category === state.currentCategory)
    : state.items;
  const el = $("items-list");
  if (!filtered.length) {
    el.innerHTML = '<div style="color:#7a7974">No items in this category yet.</div>';
    return;
  }
  el.innerHTML = filtered.map(i => `
    <div class="item-card" data-slug="${i.slug}">
      <div>
        <h3>${i.name}</h3>
        <div class="meta">${i.category} · ${i.slug} · anchor (${i.anchor_x},${i.anchor_y})</div>
        <div class="meta">${i.description || "—"}</div>
        <pre>${escapeHtml(i.program).slice(0, 200)}${i.program.length > 200 ? "…" : ""}</pre>
      </div>
      <div class="item-actions">
        <button data-edit="${i.slug}">Edit</button>
        <button data-del="${i.slug}">Delete</button>
      </div>
    </div>`).join("");
  el.querySelectorAll("[data-edit]").forEach(b => {
    b.addEventListener("click", () => openEditor(b.dataset.edit));
  });
  el.querySelectorAll("[data-del]").forEach(b => {
    b.addEventListener("click", async () => {
      if (!confirm("Delete this item?")) return;
      await api(`/api/library/${b.dataset.del}`, { method: "DELETE" });
      await refresh();
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;" }[c]));
}

function openEditor(slug) {
  const item = state.items.find(i => i.slug === slug) || null;
  state.currentItem = item;
  const p = $("preview-body");
  const isNew = !item;
  p.innerHTML = `
    <label>Name</label>
    <input id="f-name" value="${item ? escapeAttr(item.name) : ""}" />
    <label>Category</label>
    <input id="f-cat" value="${item ? escapeAttr(item.category) : "symbol"}" />
    <label>Description</label>
    <input id="f-desc" value="${item ? escapeAttr(item.description) : ""}" />
    <label>Anchor X / Y</label>
    <div style="display:flex;gap:6px">
      <input id="f-ax" value="${item ? item.anchor_x : 0}" style="flex:1" />
      <input id="f-ay" value="${item ? item.anchor_y : 0}" style="flex:1" />
    </div>
    <label>Program (drawlang)</label>
    <textarea id="f-prog" rows="10">${item ? escapeHtml(item.program) : ""}</textarea>
    <div style="display:flex;gap:6px;margin-top:8px">
      <button id="f-save" style="flex:1;padding:8px;background:#01696f;color:#fff;border:0;border-radius:4px;cursor:pointer">Save</button>
      <button id="f-preview" style="flex:1;padding:8px;border:1px solid #d4d1ca;background:#fff;border-radius:4px;cursor:pointer">Preview</button>
    </div>
    <div id="preview-out" style="margin-top:8px"></div>`;
  $("f-preview").addEventListener("click", async () => {
    const prog = $("f-prog").value;
    try {
      const res = await api("/render", {
        method: "POST",
        body: JSON.stringify({ program: prog, backend: "svg" })
      });
      $("preview-out").innerHTML = res.output || "";
    } catch (e) {
      $("preview-out").textContent = e.message;
    }
  });
  $("f-save").addEventListener("click", async () => {
    const body = {
      name: $("f-name").value.trim(),
      category: $("f-cat").value.trim(),
      description: $("f-desc").value,
      anchor_x: parseFloat($("f-ax").value) || 0,
      anchor_y: parseFloat($("f-ay").value) || 0,
      program: $("f-prog").value,
    };
    try {
      if (isNew) {
        await api("/api/library", { method: "POST", body: JSON.stringify(body) });
      } else {
        await api(`/api/library/${slug}`, { method: "PATCH", body: JSON.stringify(body) });
      }
      await refresh();
    } catch (e) { alert(e.message); }
  });
}

function escapeAttr(s) { return String(s ?? "").replace(/"/g, "&quot;"); }

$("new-btn").addEventListener("click", () => openEditor(null));
refresh();
