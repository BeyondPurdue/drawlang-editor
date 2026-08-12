"""v0.7.2 tests: insert_statement_at (text-editor Enter-to-add-line)."""

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


def _prog(canvases, slug):
    return canvases.get_canvas_program(slug, with_frame=False).strip()


def test_insert_in_middle_shifts_subsequent_seqs(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="a", program="mr,0,0;dl,10,0;ci,5,f;")
    r = cv.insert_statement_at("a", seq=1, opcode="rt", args="2,3")
    assert r["seq"] == 1
    assert r["opcode"] == "rt"
    assert _prog(cv, "a") == "mr,0,0;\nrt,2,3;\ndl,10,0;\nci,5,f;"


def test_insert_at_zero_pushes_first_row_down(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="b", program="mr,0,0;dl,10,0;")
    cv.insert_statement_at("b", seq=0, opcode="tx", args="0,hi")
    assert _prog(cv, "b") == "tx,0,hi;\nmr,0,0;\ndl,10,0;"


def test_insert_past_end_appends(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="c", program="mr,0,0;dl,10,0;")
    r = cv.insert_statement_at("c", seq=999, opcode="ci", args="3,f")
    assert r["seq"] == 2  # clamped to max+1
    assert _prog(cv, "c") == "mr,0,0;\ndl,10,0;\nci,3,f;"


def test_insert_on_empty_canvas(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="d")
    r = cv.insert_statement_at("d", seq=0, opcode="mr", args="0,0")
    assert r["seq"] == 0
    assert _prog(cv, "d") == "mr,0,0;"


def test_insert_negative_seq_clamped_to_zero(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="e", program="dl,10,0;")
    r = cv.insert_statement_at("e", seq=-5, opcode="mr", args="0,0")
    assert r["seq"] == 0
    assert _prog(cv, "e") == "mr,0,0;\ndl,10,0;"


def test_insert_is_undoable(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="f", program="mr,0,0;dl,10,0;")
    before = _prog(cv, "f")
    cv.insert_statement_at("f", seq=1, opcode="rt", args="1,2")
    assert _prog(cv, "f") != before
    cv.undo("f")
    assert _prog(cv, "f") == before


def test_insert_returns_none_for_missing_canvas(temp_db):
    cv = temp_db
    r = cv.insert_statement_at("does-not-exist", seq=0, opcode="mr", args="0,0")
    assert r is None


def test_multiple_inserts_at_same_position_stack_correctly(temp_db):
    cv = temp_db
    cv.create_canvas("t", slug="g", program="mr,0,0;dl,10,0;")
    cv.insert_statement_at("g", seq=1, opcode="tx", args="0,a")
    cv.insert_statement_at("g", seq=1, opcode="tx", args="0,b")
    cv.insert_statement_at("g", seq=1, opcode="tx", args="0,c")
    # Each new insert pushes previous ones down.
    assert _prog(cv, "g") == "mr,0,0;\ntx,0,c;\ntx,0,b;\ntx,0,a;\ndl,10,0;"
