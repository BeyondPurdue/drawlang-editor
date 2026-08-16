// account.js — self-service password change.
(function () {
  const $ = (id) => document.getElementById(id);
  const msg = $('msg');
  const submit = $('submit');

  function say(kind, text) {
    msg.textContent = text || '';
    msg.className = 'msg ' + (kind || '');
  }

  async function api(method, path, body) {
    const opts = {
      method,
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || (method + ' ' + path + ' failed'));
    return j;
  }

  // Show the current user's email in the header.
  (async () => {
    try {
      const j = await api('GET', '/api/auth/me');
      if (j && j.user) {
        $('who-email').textContent = j.user.email;
      } else {
        window.location.href = '/login';
      }
    } catch (e) {
      $('who-email').textContent = '(unknown)';
    }
  })();

  $('pwform').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const cur = $('cur').value;
    const np1 = $('np1').value;
    const np2 = $('np2').value;
    if (np1 !== np2) {
      say('err', 'the two new-password fields do not match');
      return;
    }
    if (np1.length < 8) {
      say('err', 'new password must be at least 8 characters');
      return;
    }
    if (np1 === cur) {
      say('err', 'new password must differ from the current one');
      return;
    }
    submit.disabled = true;
    say('', 'saving\u2026');
    try {
      await api('POST', '/api/auth/change-password', {
        current_password: cur,
        new_password: np1,
      });
      $('cur').value = '';
      $('np1').value = '';
      $('np2').value = '';
      say('ok', 'password changed \u2014 other devices have been signed out');
    } catch (e) {
      say('err', e.message);
    } finally {
      submit.disabled = false;
    }
  });
})();
