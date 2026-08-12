// v0.8.0.2 — externalized for CSP script-src 'self'.
(function () {
  const $ = function (id) { return document.getElementById(id); };
  const toast = function (msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 1800);
  };

  async function api(method, path, body) {
    const opts = {
      method,
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) {
      const j = await r.json().catch(function () { return {}; });
      throw new Error(j.detail || (method + ' ' + path + ' failed'));
    }
    return r.json();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function formatCreated(v) {
    if (v == null) return '';
    if (typeof v === 'number') {
      const d = new Date(v * 1000);
      return d.toISOString().substring(0, 10);
    }
    return String(v).substring(0, 10);
  }

  function row(u) {
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td>' + escapeHtml(u.email) + '</td>' +
      '<td>' + escapeHtml(u.display_name || '') + '</td>' +
      '<td><span class="pill ' + escapeHtml(u.role) + '">' + escapeHtml(u.role) + '</span></td>' +
      '<td><span class="pill ' + escapeHtml(u.status) + '">' + escapeHtml(u.status) + '</span></td>' +
      '<td>' + (u.reason ? escapeHtml(u.reason) : '') + '</td>' +
      '<td>' + formatCreated(u.created_at) + '</td>' +
      '<td class="actions"></td>';
    const actions = tr.querySelector('.actions');
    if (u.status === 'pending') {
      const b = document.createElement('button');
      b.textContent = 'Approve';
      b.className = 'approve';
      b.onclick = function () { act('approve', u); };
      actions.appendChild(b);
    }
    if (u.status !== 'disabled' && u.role !== 'admin' && u.role !== 'demo') {
      const b = document.createElement('button');
      b.textContent = 'Disable';
      b.className = 'danger';
      b.onclick = function () { act('disable', u); };
      actions.appendChild(b);
    }
    if (u.role !== 'admin' && u.role !== 'demo') {
      const b = document.createElement('button');
      b.textContent = 'Delete';
      b.className = 'danger';
      b.onclick = function () {
        if (confirm('Delete ' + u.email + ' and all their data?')) act('delete', u);
      };
      actions.appendChild(b);
    }
    return tr;
  }

  async function act(op, u) {
    try {
      await api('POST', '/api/admin/users/' + u.id + '/' + op);
      toast(op + ' ' + u.email);
      load();
    } catch (e) {
      toast(e.message);
    }
  }

  function renderTable(into, users) {
    into.innerHTML = '';
    if (!users.users.length) {
      into.innerHTML = '<div class="empty">No users.</div>';
      return;
    }
    const t = document.createElement('table');
    t.innerHTML =
      '<thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th>' +
      '<th>Reason</th><th>Created</th><th></th></tr></thead>';
    const tb = document.createElement('tbody');
    users.users.forEach(function (u) { tb.appendChild(row(u)); });
    t.appendChild(tb);
    into.appendChild(t);
  }

  async function load() {
    try {
      const me = await api('GET', '/api/auth/me');
      $('who').textContent = (me.user ? me.user.email : '') + ' · admin';
      const pending = await api('GET', '/api/admin/users?status=pending');
      const all = await api('GET', '/api/admin/users');
      renderTable($('pending'), pending);
      renderTable($('all'), all);
    } catch (e) {
      $('pending').innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + '</div>';
    }
  }

  load();
})();
