// v0.8.0.2 — externalized for CSP script-src 'self'.
(function () {
  const form = document.getElementById('regForm');
  const msg = document.getElementById('msg');
  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    msg.className = 'msg';
    msg.textContent = '';
    const body = {
      email: form.email.value.trim(),
      display_name: form.display_name.value.trim(),
      password: form.password.value,
      reason: form.reason.value.trim(),
    };
    try {
      const r = await fetch('/api/auth/register', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      const j = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        msg.classList.add('err');
        msg.textContent = j.detail || 'Registration failed';
        return;
      }
      msg.classList.add('ok');
      const status = (j.user && j.user.status) || j.status;
      if (status === 'active') {
        msg.textContent = 'Account approved. Redirecting to sign in…';
        setTimeout(function () { location.href = '/login'; }, 900);
      } else {
        msg.textContent =
          'Request received. An admin will review and activate your account.';
        form.reset();
      }
    } catch (ex) {
      msg.classList.add('err');
      msg.textContent = 'Network error: ' + ex.message;
    }
  });
})();
