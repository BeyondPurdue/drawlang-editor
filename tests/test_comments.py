"""
Conformance tests for spec §3.5 (v0.2): line comments.

Rule under test:
  - A `#` outside a `tx` string argument starts a comment that continues to
    (but does not include) the next line terminator and is stripped before
    any other lexical processing.
  - A `#` inside a `tx` string argument is literal text (because tx string
    arguments extend from a comma to the next `;`, not to a newline).
  - Comment stripping must not change the meaning or count of statements
    that are actually present.
"""

from __future__ import annotations

import pytest

from drawlang import SPEC_VERSION
from drawlang.parser import parse
from drawlang.errors import LexicalError


def test_spec_version_is_02():
    assert SPEC_VERSION == "0.2"


class TestBasicComments:
    def test_leading_comment_before_program(self):
        stmts = parse("# Frame #2 — drawing area 588x675 px\nma,355,142;")
        assert len(stmts) == 1
        assert stmts[0].opcode == "ma"
        assert stmts[0].args == [355, 142]

    def test_trailing_comment_after_statement(self):
        stmts = parse("ma,10,20; # move to top-left of frame\n")
        assert len(stmts) == 1
        assert stmts[0].opcode == "ma"

    def test_comment_between_statements(self):
        program = (
            "mr,0,158;\n"
            "# Now draw the horizontal rule\n"
            "dl,14,0;\n"
        )
        stmts = parse(program)
        assert [s.opcode for s in stmts] == ["mr", "dl"]

    def test_multiple_comment_lines(self):
        program = (
            "# Header block\n"
            "# Source: frame-1\n"
            "# Dimensions: 588x675\n"
            "ma,0,0;\n"
            "dl,588,0;\n"
        )
        stmts = parse(program)
        assert [s.opcode for s in stmts] == ["ma", "dl"]
        assert stmts[0].args == [0, 0]
        assert stmts[1].args == [588, 0]

    def test_comment_only_program(self):
        stmts = parse("# just a comment, no drawing\n")
        assert stmts == []

    def test_empty_comment(self):
        stmts = parse("#\nma,0,0;")
        assert len(stmts) == 1
        assert stmts[0].opcode == "ma"

    def test_comment_at_eof_without_newline(self):
        # No trailing newline — comment must still terminate at end of input
        stmts = parse("ma,0,0;\n# tail comment with no newline")
        assert len(stmts) == 1
        assert stmts[0].opcode == "ma"


class TestCommentInTxString:
    def test_hash_inside_tx_string_is_literal(self):
        # `tx` takes (float, string). The string tail extends to the next `;`.
        # A `#` before the `;` is part of the string, NOT a comment.
        stmts = parse("tx,12.,Section #2;")
        assert len(stmts) == 1
        assert stmts[0].opcode == "tx"
        assert stmts[0].args == [12.0, "Section #2"]

    def test_hash_inside_tx_string_with_trailing_comment(self):
        # Inside the string: literal. After `;`: comment.
        stmts = parse("tx,10.,Item #4 quantity; # inline note about item 4\n")
        assert len(stmts) == 1
        assert stmts[0].opcode == "tx"
        assert stmts[0].args == [10.0, "Item #4 quantity"]

    def test_multiple_hashes_in_tx_string(self):
        stmts = parse("tx,8.,#### bold heading ####;")
        assert stmts[0].args == [8.0, "#### bold heading ####"]


class TestCommentInvariants:
    def test_hash_mid_statement_is_still_a_lexical_error(self):
        # `#` in the middle of a non-tx statement's arguments has never been
        # legal and is not legal in v0.2 either — line comments only apply
        # outside statements (i.e., where the `#` is at a statement boundary).
        # Here `mr,0,#158` becomes `mr,0,` after comment stripping, which
        # will fail argument validation.
        with pytest.raises((LexicalError, Exception)):
            parse("mr,0,#158;")

    def test_comment_does_not_change_semicolon_count(self):
        # Regression: earlier drafts of the strip logic dropped the newline
        # too aggressively and merged statements. Make sure that never happens.
        program = "ma,0,0; # first\ndl,10,10; # second\n"
        stmts = parse(program)
        assert len(stmts) == 2

    def test_crlf_line_endings(self):
        # Windows line endings must terminate comments too
        program = "# hello\r\nma,1,2;\r\n"
        stmts = parse(program)
        assert len(stmts) == 1
        assert stmts[0].args == [1, 2]

    def test_frame_style_header_regression(self):
        # The exact shape that produced the bug the user reported
        program = (
            "# Frame #2 — drawing area 588x675 px\n"
            "ma,355,142;\n"
        )
        stmts = parse(program)
        assert len(stmts) == 1
        assert stmts[0].opcode == "ma"
        assert stmts[0].args == [355, 142]
