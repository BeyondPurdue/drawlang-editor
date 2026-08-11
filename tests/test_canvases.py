"""
Tests for the Step 3 canvases module: schema, program <-> statements
round-trip, and the read-only accessors.

Uses a temp DB per test so we don't touch the real drawings.db.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def temp_db(monkeypatch):
    """Give each test a fresh SQLite DB in a temp directory."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    monkeypatch.setenv("DRAWLANG_DB_PATH", str(db_path))

    # Force reimport so DB_PATH picks up the env var
    import importlib
    import sys

    for mod in ("editor.app.storage", "editor.app.canvases"):
        if mod in sys.modules:
            del sys.modules[mod]

    from editor.app import storage, canvases

    # Reset any cached connection from a previous test
    storage._conn = None
    storage.DB_PATH = db_path

    storage.init()
    canvases.init()
    yield {"storage": storage, "canvases": canvases, "db_path": db_path}
    if storage._conn is not None:
        storage._conn.close()
        storage._conn = None


# ---------------------------------------------------------------------------
# Parser round-trip
# ---------------------------------------------------------------------------

def test_parse_program_basic(temp_db):
    canvases = temp_db["canvases"]
    src = "mr,14,0;\ndl,1224,0;\ntz,7;"
    pairs = canvases.parse_program(src)
    assert pairs == [("mr", "14,0"), ("dl", "1224,0"), ("tz", "7")]


def test_parse_program_ignores_comments(temp_db):
    canvases = temp_db["canvases"]
    src = "# header comment\nmr,14,0;\n# another\ndl,1224,0;"
    pairs = canvases.parse_program(src)
    assert pairs == [("mr", "14,0"), ("dl", "1224,0")]


def test_parse_program_preserves_string_args(temp_db):
    canvases = temp_db["canvases"]
    src = "tx,0,BM Global A.S.;\ntx,0,Function diagram individual level;"
    pairs = canvases.parse_program(src)
    assert pairs == [
        ("tx", "0,BM Global A.S."),
        ("tx", "0,Function diagram individual level"),
    ]


def test_program_from_statements_round_trip(temp_db):
    canvases = temp_db["canvases"]
    src = "mr,14,0;\ndl,1224,0;\ntx,0,hello;"
    pairs = canvases.parse_program(src)
    rows = [
        {"opcode": op, "args": args, "seq": i}
        for i, (op, args) in enumerate(pairs)
    ]
    reconstructed = canvases.program_from_statements(rows)
    # After reparsing, we get the same pair list
    assert canvases.parse_program(reconstructed) == pairs


# ---------------------------------------------------------------------------
# Canvas CRUD
# ---------------------------------------------------------------------------

def test_empty_canvas_list(temp_db):
    canvases = temp_db["canvases"]
    assert canvases.list_canvases() == []


def test_create_and_get_canvas(temp_db):
    canvases = temp_db["canvases"]
    src = "mr,14,0;\ndl,1224,0;\ntx,0,BM Global A.S.;"
    result = canvases.create_canvas(name="My drawing", program=src)
    assert result["canvas"]["name"] == "My drawing"
    assert result["canvas"]["slug"] == "My-drawing"
    assert len(result["statements"]) == 3
    assert result["statements"][0] == {
        "id": result["statements"][0]["id"],
        "seq": 0,
        "opcode": "mr",
        "args": "14,0",
        "group_id": None,
        "meaning_tag": None,
    }


def test_get_canvas_by_id(temp_db):
    canvases = temp_db["canvases"]
    result = canvases.create_canvas(name="X", program="mr,1,2;")
    canvas_id = result["canvas"]["id"]
    fetched = canvases.get_canvas(canvas_id)
    assert fetched is not None
    assert fetched["canvas"]["id"] == canvas_id


def test_get_canvas_program_reconstructs(temp_db):
    canvases = temp_db["canvases"]
    src = "mr,14,0;\ndl,1224,0;\ntx,0,BM Global A.S.;"
    canvases.create_canvas(name="X", program=src)
    prog = canvases.get_canvas_program("X")
    assert prog is not None
    # Statements come back in program order; parse both to compare pairs
    assert canvases.parse_program(prog) == canvases.parse_program(src)


def test_get_nonexistent_canvas(temp_db):
    canvases = temp_db["canvases"]
    assert canvases.get_canvas("does-not-exist") is None
    assert canvases.get_canvas_program("does-not-exist") is None


def test_duplicate_slug_rejected(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="X", program="mr,1,2;")
    with pytest.raises(ValueError):
        canvases.create_canvas(name="X", program="mr,3,4;")


def test_delete_canvas_cascades(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="X", program="mr,1,2;\ndl,3,4;")
    assert canvases.delete_canvas("X") is True
    assert canvases.get_canvas("X") is None
    # Deleting again returns False
    assert canvases.delete_canvas("X") is False


def test_list_canvases_returns_statement_count(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="A", program="mr,1,2;\ndl,3,4;")
    canvases.create_canvas(name="B", program="mr,5,6;")
    listing = canvases.list_canvases()
    counts = {c["name"]: c["statement_count"] for c in listing}
    assert counts == {"A": 2, "B": 1}


def test_seed_from_frame_source(temp_db):
    """
    Seed a canvas from the a3-grid frame drawlang and verify that joining
    the stored statements reproduces a parse-equivalent program.
    """
    canvases = temp_db["canvases"]
    root = Path(__file__).resolve().parent.parent
    frame_src = (root / "frames" / "a3-grid.drawlang").read_text()
    canvases.create_canvas(
        name="a3-grid-copy", frame_id="a3-grid", program=frame_src
    )
    prog = canvases.get_canvas_program("a3-grid-copy")
    assert prog is not None
    assert canvases.parse_program(prog) == canvases.parse_program(frame_src)
