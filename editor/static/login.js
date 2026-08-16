// v0.8.0.4 — externalized so the Caddy CSP (script-src 'self') doesn't
// block us. Handles the sign-in form AND the "Try the demo" button on the
// landing page (both hit the same /api/auth/login endpoint).
//
// v0.8.0.4 adds a viewport gate on the demo button: the DrawLang editor is
// a three-pane workspace (primitives sidebar / editor pane / preview pane)
// that assumes a real keyboard-and-mouse desktop. Below ~1024×640 CSS px
// the layout collapses and the demo experience is bad. Instead of letting a
// phone user sign in and get a broken UI, we intercept the click, block the
// sign-in, and show a clear "come back on a bigger screen" message.
(function () {
  const form = document.getElementById('loginForm');
  const err = document.getElementById('err');
  const demoBtn = document.getElementById('demoBtn');
  const nextUrl =
    new URLSearchParams(location.search).get('next') || '/canvas-editor';

  // Minimum viewport the editor is designed for. Anything smaller than this
  // (phones, small foldables, tiny split-screens) gets a clear stop message.
  const MIN_W = 1024;
  const MIN_H = 640;

  function viewportTooSmall() {
    // Use documentElement so we ignore browser chrome; use CSS pixels so
    // hi-DPI phones aren't falsely counted as "big enough".
    const w = Math.min(
      window.innerWidth || 0,
      document.documentElement.clientWidth || 0
    );
    const h = Math.min(
      window.innerHeight || 0,
      document.documentElement.clientHeight || 0
    );
    return w < MIN_W || h < MIN_H;
  }

  // Render the size-gate notice inline where the demo button lives, so it
  // reads as a natural response to the click (no modal, no page navigation).
  function showSizeGate() {
    const actions = demoBtn && demoBtn.closest('.demo-actions');
    const container = actions ? actions.parentNode : null;
    if (!container) return;

    // Don't stack multiple notices on repeated clicks.
    let notice = document.getElementById('demo-size-gate');
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'demo-size-gate';
      notice.setAttribute('role', 'alert');
      notice.style.cssText =
        'margin-top:14px;padding:12px 14px;border:1px solid #d6a55a;' +
        'background:#fff7e6;border-radius:6px;font-size:14px;line-height:1.5;' +
        'color:#5a4300;';
      notice.innerHTML =
        '<b>The DrawLang editor needs a bigger screen.</b><br>' +
        'It’s a three‑pane workspace — primitives on the left, code in ' +
        'the middle, live preview on the right — built for a real desktop ' +
        'browser. On a phone it’s cramped and buttons overlap.<br>' +
        '<span style="display:inline-block;margin-top:6px;color:#28251d;">' +
        'Come back on a laptop or tablet (at least ' + MIN_W + ' × ' + MIN_H +
        ' pixels).</span><br>' +
        '<span style="display:inline-block;margin-top:6px;color:#5a4300;">' +
        'In the meantime you can watch the 30‑second demo above, read the ' +
        '<a href="https://github.com/BeyondPurdue/drawlang-editor/wiki" ' +
        'target="_blank" rel="noopener" style="color:#01696f;">wiki</a>, ' +
        'or skim the ' +
        '<a href="https://github.com/BeyondPurdue/drawlang-editor/blob/main/docs/spec/drawing-language-spec.md" ' +
        'target="_blank" rel="noopener" style="color:#01696f;">language spec</a>.' +
        '</span>';
      container.appendChild(notice);
    }
    // Scroll the notice into view so the user actually sees the answer to
    // their click, and not just a mysteriously dead button.
    notice.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

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
      if (viewportTooSmall()) {
        showSizeGate();
        return;
      }
      demoBtn.disabled = true;
      demoBtn.textContent = 'Signing in…';
      signIn('demo', 'demo');
    });
  }
})();
