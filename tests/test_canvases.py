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

    for mod in ("editor.app.storage", "editor.app.canvases", "editor.app.frames"):
        if mod in sys.modules:
            del sys.modules[mod]

    from editor.app import storage, canvases, frames

    # Reset any cached connection from a previous test
    storage._conn = None
    storage.DB_PATH = db_path

    storage.init()
    canvases.init()
    # v0.7: frames moved to the DB. init() seeds legacy on-disk frames so
    # tests referencing 'a3-grid' etc. keep working.
    frames.init()
    yield {"storage": storage, "canvases": canvases, "frames": frames, "db_path": db_path}
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
    Seed a canvas from the a3-grid frame drawlang and verify that the stored
    body statements alone (with_frame=False) reproduce a parse-equivalent
    program.
    """
    canvases = temp_db["canvases"]
    root = Path(__file__).resolve().parent.parent
    frame_src = (root / "frames" / "a3-grid.drawlang").read_text()
    canvases.create_canvas(
        name="a3-grid-copy", frame_id="a3-grid", program=frame_src
    )
    body = canvases.get_canvas_program("a3-grid-copy", with_frame=False)
    assert body is not None
    assert canvases.parse_program(body) == canvases.parse_program(frame_src)


def test_get_canvas_program_prepends_frame(temp_db):
    """
    When a canvas has frame_id set, get_canvas_program (default with_frame=True)
    prepends the frame's drawlang so rendering shows the frame around content.
    """
    canvases = temp_db["canvases"]
    # Seed a canvas with a small body and attach the a3-grid frame.
    canvases.create_canvas(
        name="framed", frame_id="a3-grid", program="ma,100,100;dl,10,0;"
    )
    with_frame = canvases.get_canvas_program("framed")
    without = canvases.get_canvas_program("framed", with_frame=False)
    assert with_frame is not None and without is not None
    # With-frame program is strictly longer and ends with the body.
    assert len(with_frame) > len(without)
    assert without.strip() in with_frame
    # Sanity: both parse cleanly.
    assert canvases.parse_program(with_frame)
    assert canvases.parse_program(without)


# ---------------------------------------------------------------------------
# update_canvas
# ---------------------------------------------------------------------------

def test_update_canvas_rename(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="Old name")
    res = canvases.update_canvas("Old-name", name="New name")
    assert res is not None
    assert res["name"] == "New name"
    # Slug is NOT changed automatically — rename preserves lookup.
    assert res["slug"] == "Old-name"


def test_update_canvas_slug(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="A")
    res = canvases.update_canvas("A", slug="a-renamed")
    assert res is not None
    assert res["slug"] == "a-renamed"
    assert canvases.get_canvas("a-renamed") is not None
    assert canvases.get_canvas("A") is None


def test_update_canvas_slug_collision(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="A")
    canvases.create_canvas(name="B")
    with pytest.raises(ValueError):
        canvases.update_canvas("A", slug="B")


def test_update_canvas_frame(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="X", frame_id="a3-grid")
    res = canvases.update_canvas("X", frame_id="a3-empty")
    assert res["frame_id"] == "a3-empty"
    # Empty string clears the frame.
    res = canvases.update_canvas("X", frame_id="")
    assert res["frame_id"] is None


def test_update_canvas_preserves_omitted_fields(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="Keep", frame_id="a3-grid")
    res = canvases.update_canvas("Keep", name="Keep II")
    assert res["name"] == "Keep II"
    assert res["frame_id"] == "a3-grid"  # untouched
    assert res["slug"] == "Keep"          # untouched


def test_update_canvas_noop(temp_db):
    canvases = temp_db["canvases"]
    canvases.create_canvas(name="A")
    res = canvases.update_canvas("A")
    assert res is not None
    assert res["name"] == "A"


def test_update_canvas_not_found(temp_db):
    canvases = temp_db["canvases"]
    assert canvases.update_canvas("does-not-exist", name="X") is None
