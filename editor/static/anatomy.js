// DrawLang landing-page "anatomy" animation.
// Pre-rendered frames of the AND-gate program, one per statement.
// Runs client-side only — no network calls, no sandbox integration.

'use strict';

(function () {
  // Frames auto-generated from the same interpreter used by the editor.
  // Each entry is { line: "<statement>;", svg: "<inner svg geometry>" }.
  const FRAMES = [
    { line: "ma,40,40;", svg: "" },
    { line: "rt,80,60,f,c2;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" />" },
    { line: "ma,20,80;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" />" },
    { line: "dl,20,0;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "ma,20,60;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "dl,20,0;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "ma,120,70;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "dl,20,0;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "ma,15,80;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" />" },
    { line: "ci,3,f,c1;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "ma,15,60;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "ci,3,f,c1;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "ma,145,70;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "ci,3,f,c1;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"145\" cy=\"70\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "tz,14;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"145\" cy=\"70\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "ma,58,73;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"145\" cy=\"70\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" />" },
    { line: "tx,0,AND;", svg: "<rect x=\"40\" y=\"40\" width=\"80\" height=\"60\" stroke=\"#c62828\" stroke-width=\"1.0\" fill=\"#c62828\" /> <line x1=\"20\" y1=\"80\" x2=\"40\" y2=\"80\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"20\" y1=\"60\" x2=\"40\" y2=\"60\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <line x1=\"120\" y1=\"70\" x2=\"140\" y2=\"70\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"none\" /> <circle cx=\"15\" cy=\"80\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"15\" cy=\"60\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <circle cx=\"145\" cy=\"70\" r=\"3\" stroke=\"#000000\" stroke-width=\"1.0\" fill=\"#000000\" /> <g transform=\"translate(58 73) scale(1 -1) rotate(0)\"><text x=\"0\" y=\"0\" font-family=\"sans-serif\" font-size=\"14\" fill=\"#ffffff\" font-weight=\"600\">AND</text></g>" }
  ];

  const VIEWBOX = '8 -104.0 144 68.0';
  const TYPE_MS = 28;             // ms per character while typing
  const STATEMENT_PAUSE = 320;    // ms to hold after each statement renders
  const RESET_PAUSE = 3200;       // ms to hold the final image before restart

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    const codeEl = document.getElementById('anatomy-code');
    const renderEl = document.getElementById('anatomy-render');
    if (!codeEl || !renderEl) return;

    // ── DOM structure inside the code block ────────────────────────────
    // <pre id="anatomy-code">
    //   <span class="typed"></span><span class="cursor">█</span>
    // </pre>
    // We update .typed's textContent and let CSS blink the cursor.
    let typedEl = document.createElement('span');
    typedEl.className = 'typed';
    let cursorEl = document.createElement('span');
    cursorEl.className = 'cursor';
    cursorEl.textContent = '\u2588';

    function resetDom() {
      codeEl.textContent = '';
      typedEl.textContent = '';
      codeEl.appendChild(typedEl);
      codeEl.appendChild(cursorEl);
    }

    function paint(inner) {
      // Ghost outline shown when nothing has been drawn yet, so the render
      // box doesn't look 'broken' during the very first statements which
      // only move the pen.
      const ghost = inner ? '' :
        '<rect x="40" y="40" width="80" height="60" ' +
        'stroke="#d4d1ca" stroke-width="1.0" stroke-dasharray="3 3" fill="none" />';
      renderEl.innerHTML =
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + VIEWBOX + '" ' +
        'preserveAspectRatio="xMidYMid meet" role="img" ' +
        'aria-label="AND gate being drawn statement-by-statement">' +
        '<style>line,rect,path,polyline,polygon,circle,ellipse{vector-effect:non-scaling-stroke}</style>' +
        '<g transform="scale(1 -1)">' + ghost + inner + '</g>' +
        '</svg>';
    }

    function typeLine(text, onDone) {
      // If there is already text, add a newline before typing the next line.
      const prefix = typedEl.textContent.length ? typedEl.textContent + '\n' : '';
      let i = 0;
      function step() {
        if (paused) { pendingResume = () => typeLine(text.slice(i), function () { onDone(); }); return; }
        i++;
        typedEl.textContent = prefix + text.slice(0, i);
        if (i < text.length) {
          setTimeout(step, TYPE_MS);
        } else {
          onDone();
        }
      }
      setTimeout(step, TYPE_MS);
    }

    let paused = false;
    let pendingResume = null;
    const btnEl = document.getElementById('anatomy-toggle');
    if (btnEl) {
      btnEl.addEventListener('click', function () {
        paused = !paused;
        btnEl.textContent = paused ? 'Play' : 'Pause';
        btnEl.setAttribute('aria-pressed', paused ? 'true' : 'false');
        if (!paused && pendingResume) {
          const r = pendingResume;
          pendingResume = null;
          r();
        } else if (!paused) {
          tick();
        }
      });
    }

    let idx = 0;
    function tick() {
      if (paused) { pendingResume = tick; return; }
      if (idx >= FRAMES.length) {
        setTimeout(function () {
          if (paused) { pendingResume = function () { idx = 0; resetDom(); paint(''); tick(); }; return; }
          idx = 0;
          resetDom();
          paint('');
          tick();
        }, RESET_PAUSE);
        return;
      }
      const f = FRAMES[idx];
      typeLine(f.line, function () {
        paint(f.svg);
        idx++;
        setTimeout(tick, STATEMENT_PAUSE);
      });
    }

    // Kick off — respect prefers-reduced-motion.
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      codeEl.textContent = FRAMES.map(function (f) { return f.line; }).join('\n');
      paint(FRAMES[FRAMES.length - 1].svg);
      if (btnEl) btnEl.style.display = 'none';
      return;
    }
    resetDom();
    paint('');
    tick();
  });
})();
