"""Step 5 + Step 8 tests: library CRUD and drop-on-canvas."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def db(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    monkeypatch.setenv("DRAWLANG_DB_PATH", str(db_path))
    import sys
    for mod in ("editor.app.storage", "editor.app.canvases",
                "editor.app.library"):
        if mod in sys.modules:
            del sys.modules[mod]
    from editor.app import storage, canvases, library
    storage._conn = None
    storage.DB_PATH = db_path
    storage.init()
    canvases.init()
    library.init()
    yield {"storage": storage, "canvases": canvases, "library": library}
    if storage._conn is not None:
        storage._conn.close()
        storage._conn = None


def test_create_and_get_library_item(db):
    lib = db["library"]
    item = lib.create_item(
        name="Motor M1", program="mr,0,0;dl,20,0;dl,0,20;",
        category="symbol", description="A simple motor"
    )
    assert item["slug"] == "Motor-M1"
    assert item["category"] == "symbol"
    fetched = lib.get_item("Motor-M1")
    assert fetched["program"] == "mr,0,0;dl,20,0;dl,0,20;"


def test_list_library_by_category(db):
    lib = db["library"]
    lib.create_item(name="A", program="mr,0,0;", category="symbol")
    lib.create_item(name="B", program="dl,10,0;", category="frame")
    lib.create_item(name="C", program="tx,0,x;", category="symbol")
    assert len(lib.list_items()) == 3
    assert len(lib.list_items(category="symbol")) == 2
    assert len(lib.list_items(category="frame")) == 1


def test_update_library_item(db):
    lib = db["library"]
    item = lib.create_item(name="X", program="mr,0,0;")
    updated = lib.update_item("X", {"description": "new desc",
                                     "program": "dl,5,5;"})
    assert updated["description"] == "new desc"
    assert updated["program"] == "dl,5,5;"


def test_delete_library_item(db):
    lib = db["library"]
    lib.create_item(name="X", program="mr,0,0;")
    assert lib.delete_item("X") is True
    assert lib.get_item("X") is None


def test_drop_on_canvas(db):
    canvases = db["canvases"]
    lib = db["library"]
    canvases.create_canvas(name="page1", program="")
    lib.create_item(
        name="Valve", program="mr,0,0;dl,20,0;dl,0,10;",
        category="symbol",
    )
    inserted = lib.drop_on_canvas("Valve", "page1", x=100, y=200)
    # 1 prelude ma + 3 body statements = 4 rows
    assert len(inserted) == 4
    assert inserted[0]["opcode"] == "ma"
    assert inserted[0]["args"] == "100,200"
    data = canvases.get_canvas("page1")
    assert len(data["statements"]) == 4


def test_drop_with_anchor(db):
    canvases = db["canvases"]
    lib = db["library"]
    canvases.create_canvas(name="p", program="")
    lib.create_item(
        name="Y", program="mr,0,0;dl,10,10;", anchor_x=5, anchor_y=5,
    )
    inserted = lib.drop_on_canvas("Y", "p", x=100, y=100)
    # Anchor 5,5 subtracted from drop point
    assert inserted[0]["args"] == "95,95"


def test_drop_missing_library_raises(db):
    canvases = db["canvases"]
    lib = db["library"]
    canvases.create_canvas(name="p", program="")
    with pytest.raises(KeyError):
        lib.drop_on_canvas("nope", "p", x=0, y=0)


def test_drop_missing_canvas_raises(db):
    lib = db["library"]
    lib.create_item(name="Y", program="mr,0,0;")
    with pytest.raises(KeyError):
        lib.drop_on_canvas("Y", "nope", x=0, y=0)


def test_duplicate_library_slug(db):
    lib = db["library"]
    lib.create_item(name="X", program="mr,0,0;")
    with pytest.raises(ValueError):
        lib.create_item(name="X", program="dl,5,5;")
