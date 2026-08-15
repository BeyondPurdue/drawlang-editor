// auth-badge.js — v0.8.0 minimal user badge for editor pages.
// KISS: appends a small badge to the first <header> on the page,
// showing "logged in as X · logout". No framework, no dependency.
(async () => {
  try {
    const r = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (!r.ok) return;
    const j = await r.json();
    const u = j && j.user;
    if (!u) return;

    const header = document.querySelector('header');
    if (!header) return;

    const badge = document.createElement('div');
    badge.style.cssText = [
      'margin-left:auto',
      'display:flex',
      'align-items:center',
      'gap:8px',
      'font-size:12px',
      'color:#7a7974',
      'padding:0 8px',
    ].join(';');

    const label = u.role === 'demo' ? 'demo (resets nightly)'
                : u.role === 'admin' ? (u.display_name || u.email) + ' (admin)'
                : (u.display_name || u.email);

    const who = document.createElement('span');
    who.textContent = label;
    badge.appendChild(who);

    if (u.role === 'admin') {
      const linkStyle = 'color:#01696f;text-decoration:none;';
      const a = document.createElement('a');
      a.href = '/admin/users';
      a.textContent = 'Users';
      a.style.cssText = linkStyle;
      badge.appendChild(a);
      const b = document.createElement('a');
      b.href = '/admin/stats';
      b.textContent = 'Stats';
      b.style.cssText = linkStyle;
      badge.appendChild(b);
      const d = document.createElement('a');
      d.href = '/experiments/demo-sync';
      d.textContent = 'Demo sync';
      d.title = 'How the nightly demo-account sync works';
      d.style.cssText = linkStyle;
      badge.appendChild(d);
    }

    const logout = document.createElement('a');
    logout.href = '/logout';
    logout.textContent = 'Sign out';
    logout.style.cssText = 'color:#01696f;text-decoration:none;';
    badge.appendChild(logout);

    // Prefer to sit at the very end of the header.
    header.appendChild(badge);
  } catch (_) { /* silent */ }
})();
