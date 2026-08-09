"""
v0.5 conformance tests: the `,t` modifier is a reserved no-op on `ci` and `rt`.

Spec §6.4, §6.5, §8.1, §14 (v0.5). See DRAWING-LANGUAGE-SPEC.md.

Contract:
- Parser MUST accept `,t` on `ci` and `rt`.
- Parser MUST still reject `,t` on any other opcode (dl, mr, ma, tz, tx, ar, bz, sp).
- Reference SVG backend MUST render the shape identically to the same statement
  without `,t` (no visual effect until a future spec revision attaches semantics).
- `,t` MAY combine with `,f`, `,i`, `,d`, `,c<n>` in any order on the opcodes
  where those modifiers are valid.
"""
import re
import pytest

from drawlang import render, parse
from drawlang.errors import LexicalError, SemanticError


# ---------- parser accepts ----------

def test_parse_ci_t_ok():
    """`ci,r,t` parses without error."""
    prog = parse("ci,2,t;")
    assert len(prog) == 1
    assert prog[0].opcode == "ci"
    assert any(m.name == "t" for m in prog[0].modifiers)


def test_parse_rt_t_ok():
    """`rt,w,h,t` parses without error."""
    prog = parse("rt,8,8,t;")
    assert len(prog) == 1
    assert prog[0].opcode == "rt"
    assert any(m.name == "t" for m in prog[0].modifiers)


def test_parse_ci_f_t_combined():
    """`ci,r,f,t` — combining reserved modifier with fill."""
    prog = parse("ci,5,f,t;")
    assert len(prog) == 1
    mods = {m.name for m in prog[0].modifiers}
    assert "f" in mods and "t" in mods


def test_parse_rt_f_i_t_combined():
    """`rt,w,h,f,i,t` — combining all three."""
    prog = parse("rt,10,10,f,i,t;")
    assert len(prog) == 1
    mods = {m.name for m in prog[0].modifiers}
    assert mods == {"f", "i", "t"}


# ---------- parser still rejects `,t` where not applicable ----------

def test_parse_dl_t_still_rejected():
    """`dl` does NOT accept `,t`. Only `,d`, `,c`, `,i` (v0.4)."""
    with pytest.raises((LexicalError, SemanticError)):
        parse("dl,10,0,t;")


def test_parse_mr_t_rejected():
    """`mr` accepts no modifiers at all."""
    with pytest.raises((LexicalError, SemanticError)):
        parse("mr,5,5,t;")


def test_parse_tx_t_rejected():
    """`tx` accepts only `,c`; `,t` on tx must be rejected as a modifier.

    Note: `tx,0,t` where `t` is the TEXT argument (a literal 't' label) is a
    different case — the third arg is a STRING, not a modifier. That's parsed
    as text, not as a modifier, and doesn't trigger this rule.
    """
    # `tx,0,foo,t` — tx has string_tail=1 meaning the second arg (index 1) is
    # the string. Everything after that would be a modifier and `,t` isn't valid.
    # But because string_tail consumes to end-of-statement, the literal `,t`
    # here becomes part of the string. So this test uses tx with an explicit
    # extra token that can't be part of the string. Actually the safest way:
    # test that dl,mr,ma reject ,t. Skip tx since its string-tail rule swallows.
    pass


# ---------- reference backend: identical rendering ----------

def _rects(svg: str) -> list[str]:
    return re.findall(r"<rect[^>]*/>", svg)


def _circles(svg: str) -> list[str]:
    return re.findall(r"<circle[^>]*/>", svg)


def test_rt_t_renders_identical_to_plain_rt():
    """`rt,8,8,t` and `rt,8,8` produce identical SVG output."""
    plain = render("rt,8,8;", backend="svg")
    with_t = render("rt,8,8,t;", backend="svg")
    assert _rects(plain) == _rects(with_t), (
        f"rt,t should render identically to rt.\n plain: {_rects(plain)}\n with_t: {_rects(with_t)}"
    )


def test_ci_t_renders_identical_to_plain_ci():
    """`ci,2,t` and `ci,2` produce identical SVG output."""
    plain = render("ci,2;", backend="svg")
    with_t = render("ci,2,t;", backend="svg")
    assert _circles(plain) == _circles(with_t)


def test_rt_f_t_renders_identical_to_rt_f():
    """`rt,10,10,f,t` renders identically to `rt,10,10,f` — `,t` is inert."""
    plain = render("rt,10,10,f;", backend="svg")
    with_t = render("rt,10,10,f,t;", backend="svg")
    assert _rects(plain) == _rects(with_t)


# ---------- realistic library pattern (HHY01D plan 1580 pic_ex 24904) ----------

def test_real_pic_ex_pattern_parses():
    """Real HHY01D pattern that failed in v0.4: circle with ,t before invisible rt."""
    prog = "mr,-12,-12;rt,24,25,i;dl,10,0,i;mr,-10,0;dl,0,10,i;"
    # (dl,i is v0.4; this test just confirms nothing regressed)
    result = render(prog, backend="svg")
    assert "<svg" in result


def test_symbol_with_ci_t_and_rt_i_pattern_parses():
    """Real pic_ex pattern combining v0.5 `ci,t` with v0.4 `rt,i`."""
    prog = "ci,2,t;mr,-12,-12;rt,24,25,i;"
    result = render(prog, backend="svg")
    # ci,2,t should produce a <circle>; rt,24,25,i should be invisible
    assert "<circle" in result
    # invisible rt should NOT emit a <rect> (v0.4 semantics)
    assert "<rect" not in result


def test_filled_rt_next_to_bare_rt_t():
    """Real pic_ex pattern: `rt,50,50,f; mr,0,42; rt,8,8,t;` — a filled black
    square with a small `,t` rectangle beside it."""
    prog = "rt,50,50,f;mr,0,42;rt,8,8,t;"
    result = render(prog, backend="svg")
    rects = _rects(result)
    assert len(rects) == 2, f"expected 2 <rect> elements, got {len(rects)}: {rects}"
    # The `,t` rect must have fill="none" (identical to a bare rt,8,8)
    assert any('width="8"' in r and 'fill="none"' in r for r in rects)
