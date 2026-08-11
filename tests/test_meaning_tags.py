"""Step 10 tests: semantic layer (meaning tags).

The meaning-tag column is an additive column on `statements`. It carries an
optional application-level identifier (a KKS tag, a plant loop ID, a symbol
role, etc.) alongside the drawlang statement. It is *never* interpreted by
the drawlang interpreter; it is metadata for the semantic layer only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def temp_db(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    monkeypatch.setenv("DRAWLANG_DB_PATH", str(db_path))
    import sys
    for mod in ("editor.app.storage", "editor.app.canvases"):
        if mod in sys.modules:
            del sys.modules[mod]
    from editor.app import storage, canvases
    storage._conn = None
    storage.DB_PATH = db_path
    storage.init()
    canvases.init()
    yield canvases
    if storage._conn is not None:
        storage._conn.close()
        storage._conn = None


def test_meaning_tag_defaults_to_null(temp_db):
    temp_db.create_canvas(name="c1", program="mr,1,2;")
    data = temp_db.get_canvas("c1")
    assert data["statements"][0]["meaning_tag"] is None


def test_append_with_meaning_tag(temp_db):
    temp_db.create_canvas(name="c2", program="")
    inserted = temp_db.append_statements("c2", [
        {"opcode": "mr", "args": "0,0", "meaning_tag": "motor/pump-101"},
        {"opcode": "rt", "args": "20,20", "meaning_tag": "motor/pump-101"},
        {"opcode": "tx", "args": "0,P-101", "meaning_tag": "label/pump-101"},
    ])
    assert [s["meaning_tag"] for s in inserted] == [
        "motor/pump-101", "motor/pump-101", "label/pump-101",
    ]


def test_patch_meaning_tag_sets_and_preserves(temp_db):
    temp_db.create_canvas(name="c3", program="mr,1,2;dl,10,0;")
    data = temp_db.get_canvas("c3")
    stmt_id = data["statements"][0]["id"]

    # Setting a tag.
    result = temp_db.update_statement("c3", stmt_id, {"meaning_tag": "loop-42"})
    assert result["meaning_tag"] == "loop-42"

    # A patch that touches args but not meaning_tag preserves the tag.
    result = temp_db.update_statement("c3", stmt_id, {"args": "1,2"})
    assert result["meaning_tag"] == "loop-42"
    assert result["args"] == "1,2"


def test_patch_meaning_tag_clears_when_explicit_null(temp_db):
    """This is enforced at the API layer (exclude_unset). The DB helper
    treats an explicit None as a clear when the key is present."""
    temp_db.create_canvas(name="c4", program="mr,1,2;")
    data = temp_db.get_canvas("c4")
    stmt_id = data["statements"][0]["id"]
    temp_db.update_statement("c4", stmt_id, {"meaning_tag": "x"})
    result = temp_db.update_statement("c4", stmt_id, {"meaning_tag": None})
    assert result["meaning_tag"] is None


def test_list_by_meaning_tag(temp_db):
    temp_db.create_canvas(name="c5", program="")
    temp_db.append_statements("c5", [
        {"opcode": "mr", "args": "0,0", "meaning_tag": "loop/T-01"},
        {"opcode": "dl", "args": "20,0", "meaning_tag": "loop/T-01"},
        {"opcode": "tx", "args": "0,other", "meaning_tag": "loop/P-02"},
        {"opcode": "dl", "args": "0,10"},  # untagged
    ])
    rows = temp_db.list_statements_by_meaning("c5", "loop/T-01")
    assert [r["opcode"] for r in rows] == ["mr", "dl"]
    other = temp_db.list_statements_by_meaning("c5", "loop/P-02")
    assert [r["opcode"] for r in other] == ["tx"]
    empty = temp_db.list_statements_by_meaning("c5", "loop/nonexistent")
    assert empty == []


def test_meaning_index(temp_db):
    temp_db.create_canvas(name="c6", program="")
    temp_db.append_statements("c6", [
        {"opcode": "mr", "args": "0,0", "meaning_tag": "A"},
        {"opcode": "dl", "args": "1,0", "meaning_tag": "A"},
        {"opcode": "dl", "args": "0,1", "meaning_tag": "B"},
        {"opcode": "tx", "args": "0,x"},  # untagged, must not appear
    ])
    index = temp_db.list_meaning_index("c6")
    assert index == [{"meaning_tag": "A", "count": 2}, {"meaning_tag": "B", "count": 1}]


def test_meaning_index_empty(temp_db):
    temp_db.create_canvas(name="c7", program="mr,0,0;")
    assert temp_db.list_meaning_index("c7") == []


def test_meaning_tag_not_found_canvas(temp_db):
    assert temp_db.list_statements_by_meaning("no-such-canvas", "X") == []
    assert temp_db.list_meaning_index("no-such-canvas") == []


def test_meaning_tag_survives_get_canvas_and_program(temp_db):
    """meaning_tag should be visible in get_canvas payloads. It must NOT
    appear anywhere in the drawlang program string \u2014 the language is
    unchanged, meaning_tag is purely metadata."""
    temp_db.create_canvas(name="c8", program="")
    temp_db.append_statements("c8", [
        {"opcode": "mr", "args": "0,0", "meaning_tag": "M-1"},
    ])
    data = temp_db.get_canvas("c8")
    assert data["statements"][0]["meaning_tag"] == "M-1"

    prog = temp_db.get_canvas_program("c8")
    assert prog.strip() == "mr,0,0;"
    assert "M-1" not in prog
    assert "meaning" not in prog


def test_init_is_idempotent_migration(temp_db):
    """Second init() call should be a no-op even though ALTER TABLE ran once."""
    temp_db.init()
    temp_db.init()
    # If it were not idempotent, the second ALTER would have thrown.
    temp_db.create_canvas(name="c9", program="mr,0,0;")
    data = temp_db.get_canvas("c9")
    assert "meaning_tag" in data["statements"][0]
