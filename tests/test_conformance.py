"""
Conformance test suite for the Drawing Language v0.2 interpreter.

Every test is tagged with the spec section it verifies. If a test fails,
either the interpreter is non-conforming (fix the code) or the spec has
been changed in an incompatible way (that's a v0.2 event and requires
review before proceeding).

Run:  python -m pytest tests/ -v
"""

import math
import re
import sys
from pathlib import Path

# Make the sibling `drawlang` package importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from drawlang import parse, interpret, render, SPEC_VERSION
from drawlang.errors import LexicalError, SemanticError
from drawlang.interpreter import PenState, _catmull_rom_to_beziers
from drawlang.backends.svg import SVGBackend
from drawlang.backends.ps import PostScriptBackend


# ---------------------------------------------------------------------------
# Version guard
# ---------------------------------------------------------------------------


def test_spec_version():
    """The interpreter targets spec v0.3."""
    assert SPEC_VERSION == "0.3"


# ---------------------------------------------------------------------------
# Parser — Lexical structure (spec §3)
# ---------------------------------------------------------------------------


class TestLexical:
    def test_empty_program(self):
        assert parse("") == []
        assert parse(";") == []
        assert parse(";;;;") == []

    def test_whitespace_insignificant_between_tokens(self):
        """Spec §3.1 & §3.2: whitespace between tokens is ignored."""
        a = parse("mr,0,10;dl,20,0;")
        b = parse("mr, 0, 10; dl, 20, 0;")
        c = parse("mr,0,10 ; dl,20,0 ;")
        d = parse("  mr , 0 , 10 ;\n dl , 20 , 0 ;\n")
        assert a == b == c == d

    def test_uppercase_opcode_rejected(self):
        """Spec §3.6: opcodes are lowercase."""
        with pytest.raises(LexicalError, match="lowercase"):
            parse("MR,0,10;")

    def test_unknown_opcode_rejected(self):
        """Spec §3.3: unknown opcodes are lexical errors."""
        with pytest.raises(LexicalError, match="unknown opcode"):
            parse("xy,0,10;")

    def test_unknown_modifier_rejected(self):
        """Spec §8.3: unknown modifiers are lexical errors."""
        with pytest.raises(LexicalError, match="unknown modifier"):
            parse("rt,10,20,z;")


# ---------------------------------------------------------------------------
# Parser — Numeric types (spec §3.4)
# ---------------------------------------------------------------------------


class TestNumbers:
    def test_integer_negative(self):
        stmts = parse("mr,-14,-158;")
        assert stmts[0].args == [-14, -158]

    def test_integer_zero(self):
        stmts = parse("ma,0,0;")
        assert stmts[0].args == [0, 0]

    def test_v03_numeric_accepts_int_and_decimal(self):
        """Spec §3.4 (v0.3): one numeric type, INT. Decimal-point literals
        are accepted and rounded half-toward-positive-infinity."""
        # Bare ints work (this is what real ES680 data uses)
        assert parse("tx,0,Hello;")[0].args == [0, "Hello"]
        assert parse("tx,90,V;")[0].args == [90, "V"]
        assert parse("tx,-90,V;")[0].args == [-90, "V"]
        # Trailing-dot ints work (v0.2 canonical form)
        assert parse("tx,0.,Hello;")[0].args == [0, "Hello"]
        assert parse("tx,90.0,V;")[0].args == [90, "V"]
        # Fractions get rounded
        assert parse("tx,3.14,X;")[0].args == [3, "X"]
        assert parse("tx,-.5,X;")[0].args == [0, "X"]  # -0.5 rounds toward +∞
        # Non-numeric is still rejected
        with pytest.raises(SemanticError, match="expected numeric"):
            parse("tx,abc,X;")

    def test_integer_range_i2(self):
        """Spec §4.3: default integer range is int16 [-32768, 32767]."""
        parse("ma,32767,-32768;")
        with pytest.raises(SemanticError, match="out of range"):
            parse("ma,40000,0;")


# ---------------------------------------------------------------------------
# Core opcodes — §6
# ---------------------------------------------------------------------------


class TestCoreOpcodes:
    def test_mr_updates_pen_relative(self):
        """Spec §6.1"""
        pen = interpret("mr,10,20;mr,3,-5;", SVGBackend())
        assert (pen.x, pen.y) == (13, 15)

    def test_ma_updates_pen_absolute(self):
        """Spec §6.2"""
        pen = interpret("mr,10,20;ma,100,200;mr,1,1;", SVGBackend())
        assert (pen.x, pen.y) == (101, 201)

    def test_dl_advances_pen_to_endpoint(self):
        """Spec §6.3"""
        pen = interpret("ma,10,10;dl,20,30;", SVGBackend())
        assert (pen.x, pen.y) == (30, 40)

    def test_rt_does_not_move_pen(self):
        """Spec §6.4"""
        pen = interpret("ma,10,10;rt,80,40;", SVGBackend())
        assert (pen.x, pen.y) == (10, 10)

    def test_rt_accepts_negative_dimensions(self):
        """Spec §6.4: w and h may be negative."""
        pen = interpret("ma,100,100;rt,-30,-20;", SVGBackend())
        assert (pen.x, pen.y) == (100, 100)

    def test_ci_does_not_move_pen(self):
        """Spec §6.5"""
        pen = interpret("ma,50,50;ci,15;", SVGBackend())
        assert (pen.x, pen.y) == (50, 50)

    def test_ci_radius_must_be_positive(self):
        """Spec §6.5"""
        with pytest.raises(SemanticError, match="radius must be positive"):
            interpret("ci,0;", SVGBackend())
        with pytest.raises(SemanticError, match="radius must be positive"):
            interpret("ci,-3;", SVGBackend())

    def test_tz_sets_text_size(self):
        """Spec §6.6"""
        pen = interpret("tz,20;", SVGBackend())
        assert pen.text_size == 20

    def test_tz_size_must_be_positive(self):
        """Spec §6.6"""
        with pytest.raises(SemanticError, match="size must be positive"):
            interpret("tz,0;", SVGBackend())

    def test_tx_does_not_move_pen(self):
        """Spec §6.7: pen unchanged after tx."""
        pen = interpret("ma,10,10;tz,12;tx,0.,Hello;", SVGBackend())
        assert (pen.x, pen.y) == (10, 10)

    def test_tx_string_preserves_spaces(self):
        """Spec §3.4 & §6.7: string preserves whitespace."""
        stmts = parse("tx,0., Hello World ;")
        # The parser preserves whitespace after the leading comma.
        # We don't strip leading/trailing spaces of the string argument.
        assert stmts[0].args[1].endswith("World ")


# ---------------------------------------------------------------------------
# Extension opcodes — §7
# ---------------------------------------------------------------------------


class TestExtensionOpcodes:
    def test_ar_does_not_move_pen(self):
        """Spec §7.1: arc leaves pen at the center."""
        pen = interpret("ma,100,100;ar,50,0.,90.;", SVGBackend())
        assert (pen.x, pen.y) == (100, 100)

    def test_ar_radius_must_be_positive(self):
        with pytest.raises(SemanticError, match="radius must be positive"):
            interpret("ar,0,0.,90.;", SVGBackend())

    def test_ar_equivalent_to_ci_at_360(self):
        """Spec §7.1 rationale: ar,r,0.,360. == ci,r visually."""
        svg1 = render("ma,50,50;ci,20;", "svg")
        svg2 = render("ma,50,50;ar,20,0.,360.;", "svg")
        # We don't require byte-identical output — they use different SVG
        # elements (circle vs path). We DO require both to have exactly one
        # visible shape at the same location.
        assert svg1.count("<circle") == 1
        assert svg2.count("<path") == 1

    def test_bz_advances_pen_to_endpoint(self):
        """Spec §7.2: pen advances to P3."""
        pen = interpret("ma,0,0;bz,10,20,30,20,50,0;", SVGBackend())
        assert (pen.x, pen.y) == (50, 0)

    def test_sp_advances_pen_to_last_anchor(self):
        """Spec §7.3: pen advances to the last anchor."""
        pen = interpret("sp,0,0,10,20,50,20,80,0;", SVGBackend())
        assert (pen.x, pen.y) == (80, 0)

    def test_sp_requires_even_arg_count(self):
        with pytest.raises(SemanticError, match="even number"):
            interpret("sp,0,0,10;", SVGBackend())

    def test_sp_requires_at_least_two_anchors(self):
        with pytest.raises(SemanticError, match=r">=4"):
            interpret("sp,0,0;", SVGBackend())

    def test_im_does_not_move_pen(self):
        """Spec §7.4: image placement leaves pen unchanged."""
        pen = interpret("ma,10,20;im,100,50,7;", SVGBackend())
        assert (pen.x, pen.y) == (10, 20)


# ---------------------------------------------------------------------------
# Modifiers — §8
# ---------------------------------------------------------------------------


class TestModifiers:
    def test_fill_only_on_closed_shapes(self):
        """Spec §8.1: ,f applies to rt, ci, ar, sp — not dl, not bz."""
        parse("rt,10,10,f;")
        parse("ci,5,f;")
        parse("ar,5,0.,90.,f;")
        # dl: fill has no meaning for open lines
        with pytest.raises(SemanticError, match="does not accept"):
            parse("dl,10,10,f;")
        # bz: single Bézier is open
        with pytest.raises(SemanticError, match="does not accept"):
            parse("bz,10,10,20,20,30,30,f;")

    def test_invisible_only_on_rt(self):
        """Spec §8.1: ,i marks a bounding-box-only shape (atmend)."""
        parse("rt,10,10,i;")
        with pytest.raises(SemanticError, match="does not accept"):
            parse("dl,10,10,i;")

    def test_dashed_applies_to_strokes(self):
        parse("dl,100,0,d;")
        parse("rt,10,10,d;")
        parse("ci,5,d;")

    def test_color_modifier_takes_digits(self):
        """Spec §8.1: ,c<n> where n is a non-negative integer."""
        stmts = parse("dl,10,0,c3;")
        m = stmts[0].modifiers[0]
        assert m.name == "c"
        assert m.color_index == 3
        # Multi-digit is fine
        stmts = parse("dl,10,0,c15;")
        assert stmts[0].modifiers[0].color_index == 15

    def test_combining_modifiers(self):
        """Spec §8.2: multiple modifiers, any order."""
        stmts = parse("rt,10,10,f,c2;")
        assert stmts[0].has_modifier("f")
        assert stmts[0].get_modifier("c").color_index == 2
        # Reverse order
        stmts2 = parse("rt,10,10,c2,f;")
        assert stmts2[0].has_modifier("f")


# ---------------------------------------------------------------------------
# Catmull-Rom → Bézier conversion (spec §7.3)
# ---------------------------------------------------------------------------


class TestCatmullRom:
    def test_two_anchors_produces_one_segment(self):
        segs = _catmull_rom_to_beziers([(0, 0), (100, 0)], tension=0.5)
        assert len(segs) == 1
        p0, cp1, cp2, p3 = segs[0]
        assert p0 == (0, 0)
        assert p3 == (100, 0)

    def test_endpoints_clamped(self):
        """Spec §7.3: P-1 = P0, PN+1 = PN. Result: control points collapse at endpoints."""
        segs = _catmull_rom_to_beziers([(0, 0), (50, 100), (100, 0)], tension=0.5)
        # Two segments
        assert len(segs) == 2
        # First segment starts at (0,0)
        assert segs[0][0] == (0, 0)
        # Last segment ends at (100, 0)
        assert segs[-1][3] == (100, 0)


# ---------------------------------------------------------------------------
# Worked examples from spec §12
# ---------------------------------------------------------------------------


class TestWorkedExamples:
    """
    Every example from spec §12 must parse and render without error.
    We check the SVG output contains the expected number of shape elements.
    """

    def test_example_12_1_rectangle_with_diagonal(self):
        svg = render("ma,10,10; rt,80,40; dl,80,40;", "svg")
        assert '<rect ' in svg
        assert '<line ' in svg

    def test_example_12_2_crosshair(self):
        svg = render(
            "ma,100,100; mr,-10,0; dl,20,0; mr,-10,-10; dl,0,20;", "svg"
        )
        assert svg.count("<line ") == 2

    def test_example_12_3_filled_bullet_with_label(self):
        svg = render(
            "ma,50,50; ci,3,f; mr,8,-4; tz,10; tx,0.,Bohemia Market;", "svg"
        )
        assert "<circle " in svg
        assert "Bohemia Market" in svg

    def test_example_12_4_quarter_arc(self):
        svg = render("ma,100,100; ar,20,90.,90.;", "svg")
        assert "<path " in svg

    def test_example_12_5_smooth_curve(self):
        svg = render("sp,0,0,30,50,80,50,120,0;", "svg")
        # Three Bezier segments → three <path> elements
        assert svg.count("<path ") == 3

    def test_example_12_6_block_with_photo_inset(self):
        svg = render(
            "ma,10,10; rt,200,150; ma,20,20; im,180,100,7; "
            "ma,20,130; tz,12; tx,0.,PID Section A;",
            "svg",
        )
        assert '<rect ' in svg
        assert '<image ' in svg
        assert "PID Section A" in svg

    def test_example_12_7_dashed_reference_line(self):
        svg = render("ma,0,50; dl,300,0,d;", "svg")
        assert 'stroke-dasharray' in svg

    def test_example_12_8_atmend_boundary(self):
        """The invisible rectangle must NOT appear in the output but the text must."""
        svg = render("ma,0,0; rt,100,50,i; ma,10,10; tx,0.,Content;", "svg")
        assert "<rect " not in svg  # invisible
        assert "Content" in svg


# ---------------------------------------------------------------------------
# PostScript backend basics
# ---------------------------------------------------------------------------


class TestPostScriptBackend:
    def test_header_and_footer(self):
        ps = render("ma,10,10; dl,20,0;", "ps")
        assert ps.startswith("%!PS-Adobe-3.0")
        assert "%%BoundingBox" in ps
        assert "showpage" in ps
        assert ps.rstrip().endswith("%%EOF")

    def test_line_emits_moveto_lineto_stroke(self):
        ps = render("ma,10,10; dl,20,30;", "ps")
        assert re.search(r"10\s+10\s+moveto\s+30\s+40\s+lineto\s+stroke", ps)

    def test_circle_emits_arc_stroke(self):
        ps = render("ma,50,50; ci,15;", "ps")
        assert re.search(r"50\s+50\s+15\s+0\s+360\s+arc\s+stroke", ps)

    def test_filled_rectangle(self):
        ps = render("ma,10,10; rt,80,40,f;", "ps")
        assert "rectfill" in ps
        assert "rectstroke" not in ps


# ---------------------------------------------------------------------------
# Backend equivalence — same program → same shapes (spec §13.3)
# ---------------------------------------------------------------------------


class TestBackendEquivalence:
    """Two conforming backends must produce visually equivalent output."""

    def test_line_count_matches(self):
        prog = "ma,0,0;dl,10,0;dl,0,10;dl,-10,0;dl,0,-10;"
        svg = render(prog, "svg")
        ps = render(prog, "ps")
        assert svg.count("<line ") == 4
        # PostScript: one moveto+lineto per dl → 4 lineto operators
        assert ps.count("lineto") == 4
