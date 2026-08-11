"""
v0.7 tests — DB-backed frames.

Frames used to live on disk (frames/<id>.drawlang + <id>.fields.json).
As of v0.7 they live in the ``frames`` table in drawings.db. On first
init the on-disk frames are seeded into the table so nothing existing
breaks. New frames can be created, updated, and deleted via the API.
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
    for mod in ("editor.app.storage", "editor.app.canvases",
                "editor.app.frames"):
        if mod in sys.modules:
            del sys.modules[mod]
    from editor.app import storage, canvases, frames
    storage._conn = None
    storage.DB_PATH = db_path
    storage.init()
    canvases.init()
    frames.init()
    yield {"storage": storage, "frames": frames, "db_path": db_path}
    if storage._conn is not None:
        storage._conn.close()
        storage._conn = None


def test_init_seeds_legacy_on_disk_frames(temp_db):
    """The 3 legacy files (a3-empty, a3-grid, a3-panglima) end up in the DB."""
    frames = temp_db["frames"]
    ids = {f["id"] for f in frames.list_frames()}
    # Only assert the ones known to exist as files in the repo.
    for expected in ("a3-empty", "a3-grid", "a3-panglima"):
        assert expected in ids, f"{expected!r} not seeded"


def test_get_frame_returns_drawlang(temp_db):
    frames = temp_db["frames"]
    d = frames.get_frame("a3-empty")
    assert d["id"] == "a3-empty"
    assert d["drawlang"], "frame must have drawlang source"
    assert isinstance(d["fields"], list)


def test_get_frame_missing_raises(temp_db):
    frames = temp_db["frames"]
    with pytest.raises(FileNotFoundError):
        frames.get_frame("does-not-exist")


def test_create_update_delete_frame(temp_db):
    frames = temp_db["frames"]
    created = frames.create_frame(
        frame_id="my-frame",
        name="My Frame",
        drawlang="ma,0,0;\nrt,100,50;\n",
        fields=[],
        source="test",
    )
    assert created["id"] == "my-frame"
    assert "rt,100,50" in created["drawlang"]

    updated = frames.update_frame("my-frame", name="Renamed", drawlang="ci,5;\n")
    assert updated["name"] == "Renamed"
    assert "ci,5" in updated["drawlang"]

    assert frames.delete_frame("my-frame") is True
    assert frames.delete_frame("my-frame") is False
    with pytest.raises(FileNotFoundError):
        frames.get_frame("my-frame")


def test_create_frame_rejects_duplicate_id(temp_db):
    frames = temp_db["frames"]
    frames.create_frame(frame_id="dup", name="A", drawlang="mr,1,1;\n")
    with pytest.raises(ValueError):
        frames.create_frame(frame_id="dup", name="B", drawlang="mr,2,2;\n")


def test_seed_is_idempotent(temp_db):
    """Calling init() a second time must not duplicate rows."""
    frames = temp_db["frames"]
    before = len(frames.list_frames())
    frames.init()
    frames.init()
    after = len(frames.list_frames())
    assert before == after
