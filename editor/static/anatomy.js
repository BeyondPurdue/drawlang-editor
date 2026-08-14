// DrawLang landing-page "anatomy" animation — pen-based.
//
// Same AND-gate program as before, but the render panel now shows an actual
// pen (a small pencil sprite) that walks the coordinate plane statement by
// statement. Each `ma,x,y` slides the pen across the paper with a dashed
// ghost trail (air move). Each `dl,dx,dy` draws a real black stroke growing
// from the pen tip. Shapes (`rt`, `ci`, `tx`, `tz`) briefly pulse the pen at
// the stamp origin and then materialize.
//
// The coordinate badge next to the pen always shows the current (x, y).
// No network calls, no sandbox integration — client-side only.

'use strict';

(function () {
  // Each entry is one statement of the program. `text` is what gets typed
  // into the code column; `op` and `args` drive the pen animation.
  //
  // Same AND-gate as before. Coordinates match the earlier hand-picked
  // layout so the finished picture is identical.
  const PROGRAM = [
    { text: "ma,40,40;",       op: "ma", args: [40, 40] },
    { text: "rt,80,60,f,c2;",  op: "rt", args: [80, 60, "f", "c2"] },
    { text: "ma,20,80;",       op: "ma", args: [20, 80] },
    { text: "dl,20,0;",        op: "dl", args: [20, 0] },
    { text: "ma,20,60;",       op: "ma", args: [20, 60] },
    { text: "dl,20,0;",        op: "dl", args: [20, 0] },
    { text: "ma,120,70;",      op: "ma", args: [120, 70] },
    { text: "dl,20,0;",        op: "dl", args: [20, 0] },
    { text: "ma,15,80;",       op: "ma", args: [15, 80] },
    { text: "ci,3,f,c1;",      op: "ci", args: [3, "f", "c1"] },
    { text: "ma,15,60;",       op: "ma", args: [15, 60] },
    { text: "ci,3,f,c1;",      op: "ci", args: [3, "f", "c1"] },
    { text: "ma,145,70;",      op: "ma", args: [145, 70] },
    { text: "ci,3,f,c1;",      op: "ci", args: [3, "f", "c1"] },
    { text: "tz,14;",          op: "tz", args: [14] },
    { text: "ma,64,68;",       op: "ma", args: [64, 68] },
    { text: "tx,0,AND;",       op: "tx", args: [0, "AND"] }
  ];

  // ─── Pacing ────────────────────────────────────────────────────────────
  const TYPE_MS         = 45;    // ms per character while typing
  const STATEMENT_PAUSE = 550;   // hold after the statement is fully drawn
  const RESET_PAUSE     = 4200;  // hold the final picture before restart
  const PEN_TRAVEL_MS   = 650;   // duration of a `ma` slide
  const PEN_DRAW_MS     = 650;   // duration of a `dl` stroke
  const STAMP_MS        = 240;   // brief pulse when a shape appears
  const FRAME_MS        = 16;    // ~60 fps
  const GHOST_FADE_MS   = 1200;  // how long an `ma` trail lingers

  // ─── SVG geometry ──────────────────────────────────────────────────────
  //
  // The DrawLang coordinate system is Y-up (paper coordinates). SVG is
  // Y-down, so we render everything inside `<g transform="scale(1 -1)">`
  // and pass DrawLang-space coordinates unchanged.
  //
  // Viewport picked to hold the AND-gate + a little breathing room.
  // Extra 25 units on the right so the coordinate badge (which sits at
  // pen_x + 6..~38) stays fully inside the viewport when the pen is at
  // the right edge of the scene (e.g. pin at x=145).
  const VIEWBOX = '5 -110 175 78';

  // Text scale for the coordinate badge — the outer scale is (1,-1), so we
  // need to flip Y again inside the badge to render text upright.
  const BADGE_FONT_SIZE = 5;

  // Pencil sprite drawn in DrawLang-space around origin, tip at (0,0).
  // Points UP-RIGHT so `+dx, +dy` lands the tip where we say it does.
  // The sprite is drawn as a small SVG group. It's designed at native
  // stroke width — vector-effect:non-scaling-stroke keeps outlines crisp.
  function penSprite() {
    return [
      '<g class="anatomy-pen">',
      // Wood shaft
      '<polygon points="0,0 3,3 12,12 15,9 12,6" ',
      'fill="#f4c76a" stroke="#8a6a1e" stroke-width="0.6" />',
      // Ferrule (metal band)
      '<polygon points="12,6 15,9 17,7 14,4" ',
      'fill="#c8c8c8" stroke="#666" stroke-width="0.4" />',
      // Eraser
      '<polygon points="14,4 17,7 19,5 16,2" ',
      'fill="#e07a7a" stroke="#8a3838" stroke-width="0.4" />',
      // Tip highlight
      '<polygon points="0,0 3,3 4,2 1,-1" fill="#2a2a2a" />',
      // Tiny dot at the exact tip (so the eye knows where the mark lands)
      '<circle cx="0" cy="0" r="0.9" fill="#01696f" />',
      '</g>'
    ].join('');
  }

  // Coordinate badge: rounded rect + text, positioned relative to the pen
  // tip. `x,y` are DrawLang-space. Offset by (+6, +14) so it sits above
  // and to the right of the pen sprite.
  function badge(x, y) {
    const dx = 6;
    const dy = 14;
    const label = 'x=' + Math.round(x) + '  y=' + Math.round(y);
    // Pill width sized so the monospace label fits with breathing room.
    // Empirical: at font-size 5, each char is ~3.0 units wide.
    const w = 4 + label.length * 3.0;
    const h = 7;
    return [
      '<g class="anatomy-badge" transform="translate(' +
        (x + dx) + ' ' + (y + dy) + ')">',
      // Flip Y so text renders upright inside the (1,-1) parent group.
      '<g transform="scale(1 -1)">',
      '<rect x="-1.5" y="-' + (h - 1) + '" width="' + w + '" height="' + h +
        '" rx="1.8" ry="1.8" fill="#ffffff" stroke="#01696f" stroke-width="0.4" opacity="0.95" />',
      '<text x="0.4" y="-1.6" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" ' +
        'font-size="' + BADGE_FONT_SIZE + '" fill="#01696f" font-weight="600">' +
        label + '</text>',
      '</g></g>'
    ].join('');
  }

  // Pen group at (x, y). `scale` gives us the stamp pulse.
  function penGroup(x, y, scale) {
    const s = (typeof scale === 'number') ? scale : 1;
    return '<g class="anatomy-pen-wrap" transform="translate(' + x + ' ' + y +
           ') scale(' + s + ' ' + s + ')">' + penSprite() + '</g>';
  }

  // A dashed ghost trail (grey, translucent) from (x1,y1) to (x2,y2).
  function ghostTrail(x1, y1, x2, y2, opacity) {
    return '<line class="anatomy-ghost" x1="' + x1 + '" y1="' + y1 +
           '" x2="' + x2 + '" y2="' + y2 +
           '" stroke="#7a7974" stroke-width="0.5" stroke-dasharray="1.6 1.6"' +
           ' opacity="' + opacity + '" />';
  }

  // ─── Frame rendering ───────────────────────────────────────────────────
  //
  // `committed` = array of SVG snippets for statements that have already
  //   fully executed. Kept as strings and concatenated each frame.
  // `preview`   = SVG snippet for whatever the current statement is
  //   partially drawing (a growing dl line, an in-flight ma ghost, etc.).
  // `pen`, `badge`, `trails` = overlay pieces drawn on top.
  //
  // The whole picture is re-rendered every animation frame. This is fine
  // for the small AND-gate scene.
  function svgWrap(inner) {
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + VIEWBOX + '" ' +
           'preserveAspectRatio="xMidYMid meet" role="img" ' +
           'aria-label="AND gate being drawn statement-by-statement">' +
           '<style>' +
             'line,rect,path,polyline,polygon,circle,ellipse{vector-effect:non-scaling-stroke}' +
             '.anatomy-pen-wrap{transition:transform 0ms}' +
           '</style>' +
           '<g transform="scale(1 -1)">' + inner + '</g>' +
           '</svg>';
  }

  // Static "ghost" outline of the gate rect, shown before the very first
  // rt statement fires so the empty box doesn't look broken.
  const GHOST_OUTLINE =
    '<rect x="40" y="40" width="80" height="60" ' +
    'stroke="#d4d1ca" stroke-width="1.0" stroke-dasharray="3 3" fill="none" />';

  // Committed-shape templates. `s` is the stamp scale (1 → normal, larger
  // during the pulse). Only text/circle/rect use `s`.
  function shapeRect(x, y, w, h) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
           '" stroke="#c62828" stroke-width="1.0" fill="#c62828" />';
  }
  function shapeCircle(cx, cy, r) {
    return '<circle cx="' + cx + '" cy="' + cy + '" r="' + r +
           '" stroke="#000000" stroke-width="1.0" fill="#000000" />';
  }
  function shapeLine(x1, y1, x2, y2) {
    return '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 +
           '" stroke="#000000" stroke-width="1.0" fill="none" />';
  }
  function shapeText(x, y, str) {
    // Y-flipped inside outer (1,-1) scale so text is upright.
    return '<g transform="translate(' + x + ' ' + y + ') scale(1 -1) rotate(0)">' +
           '<text x="0" y="0" font-family="sans-serif" font-size="14" ' +
           'fill="#ffffff" font-weight="600">' + str + '</text></g>';
  }

  // ─── DOM setup ─────────────────────────────────────────────────────────
  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    const codeEl = document.getElementById('anatomy-code');
    const renderEl = document.getElementById('anatomy-render');
    if (!codeEl || !renderEl) return;

    // <pre id="anatomy-code"><span class="typed"></span><span class="cursor">█</span></pre>
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

    // ── Interpreter state ─────────────────────────────────────────────
    // penX/penY track the pen's current position (DrawLang coords).
    // committed = fully-executed shapes as SVG strings.
    // trails    = array of { x1, y1, x2, y2, born } for ghost lines
    //             that fade over GHOST_FADE_MS.
    // textSize  = current font size, set by `tz`.
    let penX = 0, penY = 0;
    let committed = [];
    let trails = [];
    let textSize = 14;

    function paint(previewInner, penDrawX, penDrawY, penScale, showBadge) {
      const now = performance.now();
      // Filter and render fading trails.
      const trailSvg = trails.map(function (t) {
        const age = now - t.born;
        if (age > GHOST_FADE_MS) return '';
        const op = 0.55 * (1 - age / GHOST_FADE_MS);
        return ghostTrail(t.x1, t.y1, t.x2, t.y2, op.toFixed(3));
      }).join('');
      // Drop expired trails after we've drawn this frame.
      trails = trails.filter(function (t) { return (now - t.born) <= GHOST_FADE_MS; });

      const showGhost = committed.length === 0;
      const ghostSvg = showGhost ? GHOST_OUTLINE : '';

      const overlay =
        (showBadge === false ? '' : badge(penDrawX, penDrawY)) +
        penGroup(penDrawX, penDrawY, penScale);

      renderEl.innerHTML = svgWrap(
        ghostSvg +
        committed.join('') +
        (previewInner || '') +
        trailSvg +
        overlay
      );
    }

    // ── Typing ────────────────────────────────────────────────────────
    function typeLine(text, onDone) {
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

    // ── Tween helper ──────────────────────────────────────────────────
    // Calls onFrame(t) with t in [0,1] using ease-in-out over `durMs`.
    // Calls onDone() at the end (or immediately if paused mid-tween on
    // resume — the pending function will re-invoke tween from the start).
    function tween(durMs, onFrame, onDone) {
      const start = performance.now();
      function step() {
        if (paused) { pendingResume = function () { tween(durMs, onFrame, onDone); }; return; }
        const now = performance.now();
        const raw = Math.min(1, (now - start) / durMs);
        // ease-in-out cubic
        const t = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
        onFrame(t);
        if (raw < 1) setTimeout(step, FRAME_MS);
        else onDone();
      }
      step();
    }

    // ── Opcode implementations ────────────────────────────────────────
    function opMa(x2, y2, done) {
      const x1 = penX, y1 = penY;
      // Ghost trail is stamped after the tween ends so it fades from full
      // opacity from that moment. During the tween, show a live dashed
      // segment tracking the pen head so you see the "air move".
      tween(PEN_TRAVEL_MS,
        function (t) {
          const cx = x1 + (x2 - x1) * t;
          const cy = y1 + (y2 - y1) * t;
          penX = cx; penY = cy;
          const liveTrail = ghostTrail(x1, y1, cx, cy, 0.55);
          paint(liveTrail, cx, cy, 1, true);
        },
        function () {
          penX = x2; penY = y2;
          trails.push({ x1: x1, y1: y1, x2: x2, y2: y2, born: performance.now() });
          paint('', penX, penY, 1, true);
          done();
        });
    }

    function opDl(dx, dy, done) {
      const x1 = penX, y1 = penY;
      const x2 = x1 + dx, y2 = y1 + dy;
      tween(PEN_DRAW_MS,
        function (t) {
          const cx = x1 + (x2 - x1) * t;
          const cy = y1 + (y2 - y1) * t;
          penX = cx; penY = cy;
          const partial = shapeLine(x1, y1, cx, cy);
          paint(partial, cx, cy, 1, true);
        },
        function () {
          committed.push(shapeLine(x1, y1, x2, y2));
          penX = x2; penY = y2;
          paint('', penX, penY, 1, true);
          done();
        });
    }

    function opRt(w, h, done) {
      // The rect is anchored at the pen's current position (DrawLang
      // convention: `rt,w,h` from current pen). It fills in with a stamp
      // pulse — pen scales up briefly, then rect appears fully.
      const x = penX, y = penY;
      // Half of stamp: scale pen up to 1.35
      tween(STAMP_MS,
        function (t) { paint('', penX, penY, 1 + 0.35 * t, true); },
        function () {
          committed.push(shapeRect(x, y, w, h));
          // Second half: scale pen back down.
          tween(STAMP_MS,
            function (t) { paint('', penX, penY, 1.35 - 0.35 * t, true); },
            function () { paint('', penX, penY, 1, true); done(); });
        });
    }

    function opCi(r, done) {
      const cx = penX, cy = penY;
      tween(STAMP_MS,
        function (t) { paint('', penX, penY, 1 + 0.35 * t, true); },
        function () {
          committed.push(shapeCircle(cx, cy, r));
          tween(STAMP_MS,
            function (t) { paint('', penX, penY, 1.35 - 0.35 * t, true); },
            function () { paint('', penX, penY, 1, true); done(); });
        });
    }

    function opTz(size, done) {
      textSize = size;
      // No visible change — quick beat so the reader can see the statement
      // typed and understand what happened.
      setTimeout(done, 180);
    }

    function opTx(offset, str, done) {
      const x = penX, y = penY;
      tween(STAMP_MS,
        function (t) { paint('', penX, penY, 1 + 0.35 * t, true); },
        function () {
          committed.push(shapeText(x + offset, y, str));
          tween(STAMP_MS,
            function (t) { paint('', penX, penY, 1.35 - 0.35 * t, true); },
            function () { paint('', penX, penY, 1, true); done(); });
        });
    }

    function runOp(stmt, done) {
      switch (stmt.op) {
        case 'ma': return opMa(stmt.args[0], stmt.args[1], done);
        case 'dl': return opDl(stmt.args[0], stmt.args[1], done);
        case 'rt': return opRt(stmt.args[0], stmt.args[1], done);
        case 'ci': return opCi(stmt.args[0], done);
        case 'tz': return opTz(stmt.args[0], done);
        case 'tx': return opTx(stmt.args[0], stmt.args[1], done);
        default:   return setTimeout(done, 200);
      }
    }

    // ── Pause / play ──────────────────────────────────────────────────
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

    // ── Main loop ─────────────────────────────────────────────────────
    let idx = 0;
    function tick() {
      if (paused) { pendingResume = tick; return; }
      if (idx >= PROGRAM.length) {
        // Hide the pen for the final resting pause so it doesn't cover the
        // freshly-stamped 'AND' label. Also drop the coord badge — the
        // reader has already seen where the pen was.
        renderEl.innerHTML = svgWrap(committed.join(''));
        setTimeout(function () {
          if (paused) {
            pendingResume = function () {
              idx = 0;
              penX = 0; penY = 0;
              committed = [];
              trails = [];
              resetDom();
              paint('', penX, penY, 1, true);
              tick();
            };
            return;
          }
          idx = 0;
          penX = 0; penY = 0;
          committed = [];
          trails = [];
          resetDom();
          paint('', penX, penY, 1, true);
          tick();
        }, RESET_PAUSE);
        return;
      }
      const stmt = PROGRAM[idx];
      typeLine(stmt.text, function () {
        runOp(stmt, function () {
          idx++;
          setTimeout(tick, STATEMENT_PAUSE);
        });
      });
    }

    // ── Kick off — respect prefers-reduced-motion ─────────────────────
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // Skip the animation entirely; show the whole program + final image.
      codeEl.textContent = PROGRAM.map(function (s) { return s.text; }).join('\n');
      // Replay each op instantly to build the final scene.
      penX = 0; penY = 0; committed = []; trails = [];
      PROGRAM.forEach(function (s) {
        switch (s.op) {
          case 'ma': penX = s.args[0]; penY = s.args[1]; break;
          case 'dl':
            committed.push(shapeLine(penX, penY, penX + s.args[0], penY + s.args[1]));
            penX += s.args[0]; penY += s.args[1]; break;
          case 'rt': committed.push(shapeRect(penX, penY, s.args[0], s.args[1])); break;
          case 'ci': committed.push(shapeCircle(penX, penY, s.args[0])); break;
          case 'tx': committed.push(shapeText(penX + s.args[0], penY, s.args[1])); break;
        }
      });
      paint('', penX, penY, 1, false);
      if (btnEl) btnEl.style.display = 'none';
      return;
    }

    resetDom();
    paint('', penX, penY, 1, true);
    tick();
  });
})();
