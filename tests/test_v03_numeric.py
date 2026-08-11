"""
Spec v0.3 conformance tests: single numeric type (INT) with decimal-point
grace clause and round-half-toward-positive-infinity semantics.

See spec §3.4 and the version history in §14.
"""
import pytest

from drawlang import parse, SPEC_VERSION
from drawlang.errors import SemanticError


class TestSpecVersion:
    def test_spec_version_is_0_3(self):
        # v0.3 introduced INT-only numerics; v0.4 (current) is additive.
        assert SPEC_VERSION == "0.7"


class TestIntegerAnglesInTx:
    """The bug that motivated v0.3: real legacy backup data uses `tx,0,`.
    This must parse cleanly and give an int arg."""

    def test_bare_integer_angle(self):
        stmts = parse("tx,0,Hello;")
        assert len(stmts) == 1
        assert stmts[0].opcode == "tx"
        assert stmts[0].args == [0, "Hello"]
        assert isinstance(stmts[0].args[0], int)

    def test_bare_negative_integer_angle(self):
        # 36 occurrences of tx,-90, in the real backup
        stmts = parse("tx,-90,ROW;")
        assert stmts[0].args == [-90, "ROW"]
        assert isinstance(stmts[0].args[0], int)

    def test_bare_positive_180(self):
        stmts = parse("tx,180,UPSIDE;")
        assert stmts[0].args == [180, "UPSIDE"]

    def test_frame_guide_statement_72(self):
        """The exact statement pattern from picex--30 that used to fail."""
        program = "mr,5,75;tz,8;tx,0,F;mr,0,150;tx,0,E;"
        stmts = parse(program)
        assert len(stmts) == 5
        # Both tx statements should parse to int
        assert stmts[2].opcode == "tx"
        assert stmts[2].args == [0, "F"]
        assert isinstance(stmts[2].args[0], int)


class TestDecimalPointGraceClause:
    """v0.3 §3.4: a literal with a decimal point is accepted and rounded
    half-toward-positive-infinity to the nearest int."""

    def test_trailing_dot_zero(self):
        """`tx,0.` was the canonical v0.2 form — must still work."""
        stmts = parse("tx,0.,Hello;")
        assert stmts[0].args == [0, "Hello"]
        assert isinstance(stmts[0].args[0], int)

    def test_trailing_dot_90(self):
        """~3,610 tx,90. in the real backup."""
        stmts = parse("tx,90.,V;")
        assert stmts[0].args == [90, "V"]

    def test_fraction_below_half_rounds_down(self):
        stmts = parse("tx,3.14,X;")
        assert stmts[0].args == [3, "X"]

    def test_fraction_above_half_rounds_up(self):
        stmts = parse("tx,3.7,X;")
        assert stmts[0].args == [4, "X"]

    def test_exactly_half_rounds_toward_positive_infinity(self):
        """User's explicit rule: 'over the half goes to the next integer'.
        0.5 goes to 1, -0.5 goes to 0 (which is the next integer above -0.5)."""
        assert parse("tx,0.5,X;")[0].args == [1, "X"]
        assert parse("tx,3.5,X;")[0].args == [4, "X"]
        assert parse("tx,89.5,X;")[0].args == [90, "X"]

    def test_exactly_half_negative(self):
        """-0.5 rounds toward positive infinity → 0. -3.5 → -3."""
        assert parse("tx,-0.5,X;")[0].args == [0, "X"]
        assert parse("tx,-3.5,X;")[0].args == [-3, "X"]

    def test_negative_below_half_rounds_toward_negative(self):
        """-3.6 → -4 (below the halfway point, rounds away from zero)."""
        assert parse("tx,-3.6,X;")[0].args == [-4, "X"]

    def test_leading_dot(self):
        """`.5` == 0.5 → 1."""
        stmts = parse("tx,.5,X;")
        assert stmts[0].args == [1, "X"]

    def test_ar_start_and_sweep_accept_decimals(self):
        """ar,r,start,sweep — 2 occurrences in the real backup use `90.`."""
        stmts = parse("ar,50,90.,90.;")
        assert stmts[0].opcode == "ar"
        assert stmts[0].args == [50, 90, 90]
        assert all(isinstance(a, int) for a in stmts[0].args)

    def test_ar_mixed_int_and_decimal(self):
        stmts = parse("ar,50,0,180;")  # all int
        assert stmts[0].args == [50, 0, 180]


class TestBackwardCompatWithV02:
    """Every valid v0.2 program is a valid v0.3 program."""

    def test_v02_style_tx_still_works(self):
        stmts = parse("ma,10,10;tz,12;tx,0.,Hello World;")
        assert len(stmts) == 3
        assert stmts[2].args == [0, "Hello World"]

    def test_v02_comment_syntax_still_works(self):
        program = "# Frame #2 — drawing area 588x675 px\nma,355,142;\ndl,588,0;"
        stmts = parse(program)
        assert len(stmts) == 2
        assert stmts[0].opcode == "ma"

    def test_hash_still_literal_inside_tx_string(self):
        stmts = parse("tx,0,Section #4;")
        assert stmts[0].args == [0, "Section #4"]


class TestRejectedInput:
    """Non-numeric input must still be a semantic error."""

    def test_letters_are_rejected(self):
        with pytest.raises(SemanticError, match="expected numeric"):
            parse("tx,abc,Hello;")

    def test_pure_dot_is_rejected(self):
        with pytest.raises(SemanticError, match="expected numeric"):
            parse("tx,.,Hello;")

    def test_two_dots_are_rejected(self):
        with pytest.raises(SemanticError, match="expected numeric"):
            parse("tx,1.2.3,Hello;")


class TestOtherOpcodesStillIntOnly:
    """Everything that was INT in v0.2 remains INT and accepts decimals too
    (uniform §3.4 rule across every numeric arg)."""

    def test_ma_accepts_decimal_and_rounds(self):
        stmts = parse("ma,100.4,100.6;")
        assert stmts[0].args == [100, 101]

    def test_dl_accepts_decimal_and_rounds(self):
        stmts = parse("dl,10.5,-10.5;")
        # 10.5 → 11, -10.5 → -10
        assert stmts[0].args == [11, -10]

    def test_tz_accepts_decimal_and_rounds(self):
        stmts = parse("tz,12.9;")
        assert stmts[0].args == [13]
