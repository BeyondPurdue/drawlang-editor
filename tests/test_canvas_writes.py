"""Step 4 tests: statement write API."""

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


def test_append_statements(temp_db):
    temp_db.create_canvas(name="x", program="mr,1,2;")
    inserted = temp_db.append_statements("x", [
        {"opcode": "dl", "args": "10,0"},
        {"opcode": "tx", "args": "0,hello"},
    ])
    assert len(inserted) == 2
    assert inserted[0]["seq"] == 1
    assert inserted[1]["seq"] == 2
    data = temp_db.get_canvas("x")
    assert len(data["statements"]) == 3


def test_append_program(temp_db):
    temp_db.create_canvas(name="x", program="mr,1,2;")
    inserted = temp_db.append_program("x", "dl,10,0;\ntx,0,hi;")
    assert len(inserted) == 2
    prog = temp_db.get_canvas_program("x")
    assert temp_db.parse_program(prog) == [
        ("mr", "1,2"), ("dl", "10,0"), ("tx", "0,hi"),
    ]


def test_update_statement(temp_db):
    result = temp_db.create_canvas(name="x", program="mr,1,2;\ndl,10,0;")
    stmt_id = result["statements"][0]["id"]
    updated = temp_db.update_statement("x", stmt_id, {"args": "99,99"})
    assert updated["args"] == "99,99"
    prog = temp_db.get_canvas_program("x")
    assert "mr,99,99" in prog


def test_delete_statement(temp_db):
    result = temp_db.create_canvas(name="x", program="mr,1,2;\ndl,10,0;\ntx,0,hi;")
    stmt_id = result["statements"][1]["id"]  # dl
    assert temp_db.delete_statement("x", stmt_id) is True
    data = temp_db.get_canvas("x")
    assert len(data["statements"]) == 2
    ops = [s["opcode"] for s in data["statements"]]
    assert ops == ["mr", "tx"]


def test_reorder_statements(temp_db):
    result = temp_db.create_canvas(name="x", program="mr,1,2;\ndl,10,0;\ntx,0,hi;")
    ids = [s["id"] for s in result["statements"]]
    # Reverse
    assert temp_db.reorder_statements("x", list(reversed(ids))) is True
    data = temp_db.get_canvas("x")
    ops = [s["opcode"] for s in data["statements"]]
    assert ops == ["tx", "dl", "mr"]


def test_replace_program(temp_db):
    temp_db.create_canvas(name="x", program="mr,1,2;\ndl,10,0;")
    data = temp_db.replace_program("x", "tx,0,new only;")
    assert len(data["statements"]) == 1
    assert data["statements"][0]["opcode"] == "tx"


def test_append_to_missing_canvas(temp_db):
    with pytest.raises(KeyError):
        temp_db.append_statements("does-not-exist", [{"opcode": "mr", "args": "1,2"}])


def test_update_missing_statement(temp_db):
    temp_db.create_canvas(name="x", program="mr,1,2;")
    assert temp_db.update_statement("x", 9999, {"args": "5,5"}) is None


def test_delete_missing_statement(temp_db):
    temp_db.create_canvas(name="x", program="mr,1,2;")
    assert temp_db.delete_statement("x", 9999) is False


def test_writes_bump_updated_at(temp_db):
    result = temp_db.create_canvas(name="x", program="mr,1,2;")
    original = result["canvas"]["updated_at"]
    import time; time.sleep(0.01)
    temp_db.append_statements("x", [{"opcode": "dl", "args": "1,1"}])
    updated = temp_db.get_canvas("x")["canvas"]["updated_at"]
    assert updated > original
