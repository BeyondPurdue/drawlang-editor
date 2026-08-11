"""
Spec v0.6 tests — palette model and paper/ink asymmetry.

Locks in the v0.6 backend semantics:

  * Palette index 0 = paper (invisible fill).
  * Palette index 1 = ink (default stroke/text color, black in the reference palette).
  * Bare `,f` (no `,c<n>`) defaults its fill index to 0 (paper) and MUST render as
    invisible — the shape is an outline only.
  * `,f,c0` is equivalent to bare `,f` (explicit paper fill).
  * `,f,c<n>` with n >= 1 fills with palette[n].
  * Stroke with no `,c<n>` defaults to ink; stroke `,c0` falls back to ink so it stays
    visible.

Motivated by real legacy pic_ex symbols (e.g. `pic_ex -1`: `rt,1224,854,f`,
`rt,1222,852,f`) whose bare `,f` rectangles were being rendered as large solid
black blocks under v0.5, which is not what the source HMI does.
"""

from __future__ import annotations

import re

import drawlang
from drawlang import render


# ---------------------------------------------------------------------------
# Version guard
# ---------------------------------------------------------------------------


def test_spec_version_is_06():
    assert drawlang.SPEC_VERSION == "0.7"
    assert drawlang.__version__.startswith("0.7")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SHAPE_RE = re.compile(r"<(rect|circle|line|path)[^/]*/>")


def _shapes(svg: str) -> list[str]:
    return [m.group(0) for m in _SHAPE_RE.finditer(svg)]


def _first_shape(svg: str) -> str:
    shapes = _shapes(svg)
    assert shapes, f"no shape emitted in SVG:\n{svg}"
    return shapes[0]


def _attr(shape: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', shape)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# rt — rectangle
# ---------------------------------------------------------------------------


def test_rt_bare_f_is_invisible_fill():
    """rt,W,H,f with no ,c<n> must render as outline only (fill=none)."""
    svg = render("rt,100,50,f;")
    rect = _first_shape(svg)
    assert _attr(rect, "fill") == "none", rect
    # stroke should be present and non-none
    assert _attr(rect, "stroke") not in (None, "none"), rect


def test_rt_f_c0_is_invisible_fill():
    """rt,W,H,f,c0 is explicit paper — same as bare ,f."""
    svg = render("rt,100,50,f,c0;")
    rect = _first_shape(svg)
    assert _attr(rect, "fill") == "none", rect


def test_rt_f_c1_fills_with_ink():
    """rt,W,H,f,c1 fills with ink (black in the reference palette)."""
    svg = render("rt,100,50,f,c1;")
    rect = _first_shape(svg)
    assert _attr(rect, "fill") == "#000000", rect


def test_rt_f_c2_fills_with_palette_2():
    """rt,W,H,f,c2 fills with palette index 2 (project-defined; red in reference)."""
    svg = render("rt,100,50,f,c2;")
    rect = _first_shape(svg)
    fill = _attr(rect, "fill")
    assert fill and fill.startswith("#") and fill != "#000000", rect
    # stroke should match fill for a colored ,c<n> shape
    assert _attr(rect, "stroke") == fill, rect


def test_rt_no_fill_modifier_still_outline_only():
    """rt,W,H with no ,f is outline only (regression check — behavior unchanged)."""
    svg = render("rt,100,50;")
    rect = _first_shape(svg)
    assert _attr(rect, "fill") == "none", rect


def test_rt_f_t_combined_is_still_invisible_fill():
    """,f and ,t may be combined; ,t is a no-op (v0.5), ,f still resolves to paper."""
    svg = render("rt,100,50,f,t;")
    rect = _first_shape(svg)
    assert _attr(rect, "fill") == "none", rect


# ---------------------------------------------------------------------------
# ci — circle
# ---------------------------------------------------------------------------


def test_ci_bare_f_is_invisible_fill():
    svg = render("ci,25,f;")
    circle = _first_shape(svg)
    assert circle.startswith("<circle"), circle
    assert _attr(circle, "fill") == "none", circle


def test_ci_f_c0_is_invisible_fill():
    svg = render("ci,25,f,c0;")
    circle = _first_shape(svg)
    assert _attr(circle, "fill") == "none", circle


def test_ci_f_c1_fills_with_ink():
    svg = render("ci,25,f,c1;")
    circle = _first_shape(svg)
    assert _attr(circle, "fill") == "#000000", circle


def test_ci_f_c2_fills_with_palette_2():
    svg = render("ci,25,f,c2;")
    circle = _first_shape(svg)
    fill = _attr(circle, "fill")
    assert fill and fill.startswith("#") and fill != "#000000", circle


# ---------------------------------------------------------------------------
# Stroke defaults (paper/ink asymmetry)
# ---------------------------------------------------------------------------


def test_bare_dl_strokes_with_ink():
    """A bare dl must draw a visible line — stroke defaults to ink, not paper."""
    svg = render("dl,50,0;")
    line = _first_shape(svg)
    assert line.startswith("<line"), line
    assert _attr(line, "stroke") == "#000000", line


def test_dl_c0_falls_back_to_ink_so_stroke_stays_visible():
    """Explicit ,c0 on a stroke must fall back to ink — never render an invisible stroke."""
    svg = render("dl,50,0,c0;")
    line = _first_shape(svg)
    assert _attr(line, "stroke") == "#000000", line


def test_dl_c2_strokes_with_palette_2():
    svg = render("dl,50,0,c2;")
    line = _first_shape(svg)
    stroke = _attr(line, "stroke")
    assert stroke and stroke != "#000000" and stroke != "none", line


# ---------------------------------------------------------------------------
# Real legacy pattern: pic_ex -1 title-block rectangles
# ---------------------------------------------------------------------------


def test_real_picex_minus_1_title_block_pattern_is_outline_only():
    """The two rectangles from pic_ex -1 that made v0.5 render as a solid black block."""
    prog = "ma,0,0; rt,1224,854,f; ma,1,1; rt,1222,852,f;"
    svg = render(prog)
    rects = [s for s in _shapes(svg) if s.startswith("<rect")]
    assert len(rects) == 2, svg
    for r in rects:
        assert _attr(r, "fill") == "none", f"solid fill leaked back in: {r}"
        assert _attr(r, "stroke") == "#000000", f"stroke should still be visible: {r}"


def test_real_legacy_ci_t_pattern_still_renders_outline_only():
    """The HHY01D pattern: ci,2,t is an outline circle in ink."""
    svg = render("ci,2,t;")
    circle = _first_shape(svg)
    assert _attr(circle, "fill") == "none", circle
    assert _attr(circle, "stroke") == "#000000", circle
