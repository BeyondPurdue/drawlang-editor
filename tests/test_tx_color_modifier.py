"""
Regression test for the `tx` color-modifier drop bug (fixed in v0.7).

Root cause: `_split_with_string_tail` used `tail.split(",", string_index + 1)`.
For `tx` (string_index=1), a statement with exactly two commas in its tail —
e.g. `tx,0,AND,c8` — has exactly `string_index + 1` commas, so that maxsplit
fully separated it into three atomic parts `['0', 'AND', 'c8']` instead of
gluing the text and its trailing modifier together as `['0', 'AND,c8']`.
`remainder` was then read from `parts[string_index]` (`'AND'`), silently
discarding the `c8` modifier with no error — the statement still parsed
"successfully", just with the wrong (default ink) color.

The fix changes the maxsplit to `string_index` (not `string_index + 1`),
which always glues the text + trailing modifier into one element regardless
of how many commas it contains.
"""
from drawlang import parse


def _color_index(stmt):
    """Extract the color index from a statement's modifier list, if any."""
    for mod in stmt.modifiers:
        if mod.name == "c":
            return mod.color_index
    return None


def test_tx_color_modifier_no_internal_comma():
    """`tx,0,AND,c8;` must apply the c8 color modifier to the text."""
    stmts = parse("tx,0,AND,c8;")
    assert len(stmts) == 1
    stmt = stmts[0]
    assert stmt.args == [0, "AND"]
    assert _color_index(stmt) == 8


def test_tx_color_modifier_with_internal_comma():
    """Text containing a literal comma must still parse and keep its color."""
    stmts = parse("tx,0,Hello, World!,c2;")
    stmt = stmts[0]
    assert stmt.args == [0, "Hello, World!"]
    assert _color_index(stmt) == 2


def test_tx_no_color_modifier_still_works():
    """A bare `tx,0,TEXT;` (no trailing color) must be unaffected by the fix."""
    stmts = parse("tx,0,No color here;")
    stmt = stmts[0]
    assert stmt.args == [0, "No color here"]
    assert _color_index(stmt) is None


def test_tx_text_ending_in_digits_not_mistaken_for_color():
    """Trailing digits that aren't a `,c<n>` modifier must stay part of the text."""
    stmts = parse("tx,0,Ends with digits c8;")
    stmt = stmts[0]
    assert stmt.args == [0, "Ends with digits c8"]
    assert _color_index(stmt) is None
