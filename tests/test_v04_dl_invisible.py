"""
Spec v0.4 conformance tests: the `dl` opcode accepts the `,i` (invisible)
modifier.

Semantics (spec §6.3, v0.4):
  * The pen advances to `(current_x + dx, current_y + dy)`, just like a
    visible `dl`.
  * Both endpoints contribute to the bounding-box accumulator (just like
    `rt,W,H,i`).
  * No visible mark is emitted — the SVG backend must skip the
    `<line>` element.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from drawlang import parse, render, SPEC_VERSION, __version__


class TestSpecVersion:
    def test_spec_version_is_v04(self) -> None:
        assert SPEC_VERSION == "0.7"
        assert __version__.startswith("0.7")


class TestDlInvisibleParses:
    def test_dl_i_parses(self) -> None:
        """`dl,X,Y,i` must be accepted by the parser (v0.3 rejected it)."""
        stmts = parse("ma,0,0; dl,10,0,i;")
        assert len(stmts) == 2
        assert stmts[1].opcode == "dl"
        assert stmts[1].modifiers[0].name == "i"

    def test_dl_i_combined_with_other_modifiers(self) -> None:
        """`dl` accepts `i`, `d`, `c` — combinations must parse."""
        parse("ma,0,0; dl,5,5,i;")
        parse("ma,0,0; dl,5,5,d;")
        parse("ma,0,0; dl,5,5,c2;")
        parse("ma,0,0; dl,5,5,i,c1;")
        parse("ma,0,0; dl,5,5,d,c3;")


class TestDlInvisibleRendering:
    def test_dl_i_emits_no_line_element(self) -> None:
        """The SVG output must NOT contain a <line> for an invisible dl."""
        svg_visible = render("ma,0,0; dl,10,0;", backend="svg")
        svg_invisible = render("ma,0,0; dl,10,0,i;", backend="svg")
        assert "<line" in svg_visible
        assert "<line" not in svg_invisible

    def test_dl_i_advances_pen(self) -> None:
        """Pen must advance so subsequent relative ops start at the endpoint."""
        # Path: (0,0) --invisible--> (10,0) --visible--> (10,5)
        # If pen didn't advance, the visible line would start at (0,0).
        svg = render("ma,0,0; dl,10,0,i; dl,0,5;", backend="svg")
        # The visible line goes from (10,0) to (10,5)
        m = re.search(
            r'<line[^>]*x1="([^"]+)"[^>]*y1="([^"]+)"[^>]*x2="([^"]+)"[^>]*y2="([^"]+)"',
            svg,
        )
        assert m, f"expected one <line> in SVG, got: {svg}"
        x1, y1, x2, y2 = m.groups()
        assert x1 == "10" and y1 == "0"
        assert x2 == "10" and y2 == "5"

    def test_dl_i_contributes_to_bounding_box(self) -> None:
        """Bounding-box accumulator must include invisible endpoints so viewBox fits."""
        svg = render("ma,0,0; dl,100,50,i;", backend="svg")
        m = re.search(r'viewBox="([^"]+)"', svg)
        assert m, "viewBox missing"
        parts = [float(p) for p in m.group(1).split()]
        _, _, w, h = parts
        assert w >= 100, f"viewBox width {w} does not span 100 units"
        assert h >= 50, f"viewBox height {h} does not span 50 units"

    def test_pic_ex_24904_pattern_renders(self) -> None:
        """Real legacy pic_ex 24904 pattern — the case that motivated v0.4."""
        prog = "ma,50,50; mr,-12,-12; rt,24,25,i; dl,10,0,i; mr,-10,0; dl,0,10,i;"
        svg = render(prog, backend="svg")
        # All shapes are invisible — nothing should render visibly
        assert "<line" not in svg
        assert "<rect" not in svg


class TestBackwardCompatibility:
    def test_v03_programs_still_valid_in_v04(self) -> None:
        """Every v0.3 program must remain valid in v0.4."""
        # v0.3 dl with c and d modifiers still works
        parse("ma,0,0; dl,10,10,d;")
        parse("ma,0,0; dl,10,10,c0;")
        # v0.3 dl without any modifier still works
        parse("ma,0,0; dl,10,10;")
        # Rendering still produces a <line>
        assert "<line" in render("ma,0,0; dl,10,10;", backend="svg")

    def test_dl_still_rejects_fill_modifier(self) -> None:
        """`,f` is still invalid on `dl` (open path) — no v0.4 change here."""
        from drawlang.errors import SemanticError
        with pytest.raises(SemanticError, match="does not accept"):
            parse("dl,10,10,f;")
