// v0.8.0.3 — externalized so the Caddy CSP (script-src 'self') doesn't
// block us. Handles the sign-in form AND the "Try the demo" button on the
// landing page (both hit the same /api/auth/login endpoint).
(function () {
  const form = document.getElementById('loginForm');
  const err = document.getElementById('err');
  const demoBtn = document.getElementById('demoBtn');
  const nextUrl =
    new URLSearchParams(location.search).get('next') || '/canvas-editor';

  async function signIn(email, password) {
    err.textContent = '';
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email: email, password: password }),
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
  }

  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      signIn(form.email.value.trim(), form.password.value);
    });
  }

  if (demoBtn) {
    demoBtn.addEventListener('click', function (e) {
      e.preventDefault();
      demoBtn.disabled = true;
      demoBtn.textContent = 'Signing in…';
      signIn('demo', 'demo');
    });
  }
})();
