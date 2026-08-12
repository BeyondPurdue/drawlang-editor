"""v0.7 tests: server-side undo/redo history + duplicate_canvas."""

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


# ---------------------------------------------------------------------------
# Undo / Redo — every mutation must be reversible via history stack.
# ---------------------------------------------------------------------------

def test_undo_reverses_append(temp_db):
    temp_db.create_canvas(name="h", slug="h1")
    temp_db.append_program("h1", "mr,0,0;")
    temp_db.append_program("h1", "dl,10,10;")
    assert temp_db.get_canvas_program("h1", with_frame=False).strip() == "mr,0,0;\ndl,10,10;"
    temp_db.undo("h1")
    assert temp_db.get_canvas_program("h1", with_frame=False).strip() == "mr,0,0;"
    temp_db.undo("h1")
    assert temp_db.get_canvas_program("h1", with_frame=False).strip() == ""


def test_redo_reapplies_undone_edit(temp_db):
    temp_db.create_canvas(name="h", slug="h1")
    temp_db.append_program("h1", "mr,0,0;")
    temp_db.append_program("h1", "dl,10,10;")
    temp_db.undo("h1")
    temp_db.redo("h1")
    assert temp_db.get_canvas_program("h1", with_frame=False).strip() == "mr,0,0;\ndl,10,10;"


def test_new_mutation_clears_redo_stack(temp_db):
    temp_db.create_canvas(name="h", slug="h1")
    temp_db.append_program("h1", "mr,0,0;")
    temp_db.append_program("h1", "dl,10,10;")
    temp_db.undo("h1")
    assert temp_db.history_depths("h1")["redo_depth"] == 1
    # Any new mutation must invalidate redo history (standard editor semantics).
    temp_db.append_program("h1", "rt,5,5;")
    assert temp_db.history_depths("h1")["redo_depth"] == 0
    assert temp_db.history_depths("h1")["undo_depth"] >= 1


def test_history_depths_shape(temp_db):
    temp_db.create_canvas(name="h", slug="h1")
    d = temp_db.history_depths("h1")
    assert d == {"undo_depth": 0, "redo_depth": 0}
    temp_db.append_program("h1", "mr,0,0;")
    d = temp_db.history_depths("h1")
    assert d["undo_depth"] == 1 and d["redo_depth"] == 0


def test_undo_on_empty_stack_returns_none(temp_db):
    temp_db.create_canvas(name="h", slug="h1")
    assert temp_db.undo("h1") is None
    assert temp_db.redo("h1") is None


def test_delete_and_replace_program_are_undoable(temp_db):
    temp_db.create_canvas(name="h", slug="h1", program="mr,0,0;dl,10,10;")
    temp_db.replace_program("h1", "ci,5,f;")
    assert temp_db.get_canvas_program("h1", with_frame=False).strip() == "ci,5,f;"
    temp_db.undo("h1")
    assert "mr,0,0;" in temp_db.get_canvas_program("h1", with_frame=False)


def test_history_isolated_between_canvases(temp_db):
    temp_db.create_canvas(name="a", slug="a1")
    temp_db.create_canvas(name="b", slug="b1")
    temp_db.append_program("a1", "mr,0,0;")
    assert temp_db.history_depths("a1")["undo_depth"] == 1
    assert temp_db.history_depths("b1")["undo_depth"] == 0


# ---------------------------------------------------------------------------
# duplicate_canvas — deep copy including statements and frame binding.
# ---------------------------------------------------------------------------

def test_duplicate_canvas_copies_program(temp_db):
    temp_db.create_canvas(name="src", slug="src", program="mr,1,2;dl,3,4;")
    dup = temp_db.duplicate_canvas("src", new_slug="dst")
    assert dup["canvas"]["slug"] == "dst"
    assert temp_db.get_canvas_program("dst", with_frame=False).strip() \
        == temp_db.get_canvas_program("src", with_frame=False).strip()


def test_duplicate_canvas_starts_with_empty_history(temp_db):
    temp_db.create_canvas(name="src", slug="src", program="mr,1,2;")
    temp_db.append_program("src", "dl,3,4;")  # 1 undo entry in source
    temp_db.duplicate_canvas("src", new_slug="dst")
    # duplicate itself is a create_canvas call, which does NOT go through the
    # mutation snapshot path — no history should exist on the copy.
    assert temp_db.history_depths("dst") == {"undo_depth": 0, "redo_depth": 0}


def test_duplicate_canvas_slug_collision(temp_db):
    temp_db.create_canvas(name="src", slug="src")
    temp_db.create_canvas(name="other", slug="other")
    with pytest.raises(ValueError):
        temp_db.duplicate_canvas("src", new_slug="other")


def test_duplicate_canvas_missing_source(temp_db):
    with pytest.raises(KeyError):
        temp_db.duplicate_canvas("nope", new_slug="whatever")
