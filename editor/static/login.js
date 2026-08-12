// v0.8.0.2 — externalized so the Caddy CSP (script-src 'self') doesn't
// block us. Same behaviour as the previous inline <script>.
(function () {
  const form = document.getElementById('loginForm');
  const err = document.getElementById('err');
  const nextUrl =
    new URLSearchParams(location.search).get('next') || '/canvas-editor';
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    err.textContent = '';
    const body = {
      email: form.email.value.trim(),
      password: form.password.value,
    };
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const j = await r.json().catch(function () { return {}; });
        err.textContent = j.detail || 'Sign in failed';
        return;
      }
      window.location.href = nextUrl;
    } catch (ex) {
      err.textContent = 'Network error: ' + ex.message;
    }
  });
})();
