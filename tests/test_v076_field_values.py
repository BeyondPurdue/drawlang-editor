"""
v0.7.6 tests — canvas field_values + frame token substitution.

Backend contract:
- `POST /api/canvases {frame_id, field_values}` stores field_values as JSON.
- `PATCH /api/canvases/{id} {field_values}` updates them.
- `GET /api/canvases/{id}/program` substitutes `{{name}}` tokens in the
  frame's drawlang using field_values (frame field `default` as fallback).
- `GET /api/frames/{id}/tokens` returns declared / undeclared tokens.
- Canvas body drawlang is NEVER substituted.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "editor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "editor"))


@pytest.fixture()
def temp_db(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    monkeypatch.setenv("DRAWLANG_DB_PATH", str(db_path))

    import importlib
    import sys

    for mod in ("editor.app.storage", "editor.app.canvases", "editor.app.frames"):
        if mod in sys.modules:
            del sys.modules[mod]

    from editor.app import storage, canvases, frames

    storage._conn = None
    storage.DB_PATH = db_path
    storage.init()
    canvases.init()
    frames.init()
    yield {"storage": storage, "canvases": canvases, "frames": frames}
    if storage._conn is not None:
        storage._conn.close()
        storage._conn = None


def test_field_values_default_is_empty_dict(temp_db):
    canvases = temp_db["canvases"]
    c = canvases.create_canvas("plain")
    assert c["canvas"]["field_values"] == {}


def test_field_values_persist_on_create(temp_db):
    canvases = temp_db["canvases"]
    c = canvases.create_canvas(
        "plate-1",
        field_values={"drawing_no": "PA-001", "revision": "A"},
    )
    got = canvases.get_canvas(c["canvas"]["id"])
    assert got["canvas"]["field_values"] == {"drawing_no": "PA-001", "revision": "A"}


def test_field_values_update_via_update_canvas(temp_db):
    canvases = temp_db["canvases"]
    c = canvases.create_canvas("p", field_values={"a": "1"})
    canvases.update_canvas(c["canvas"]["id"], field_values={"a": "2", "b": "3"})
    got = canvases.get_canvas(c["canvas"]["id"])
    assert got["canvas"]["field_values"] == {"a": "2", "b": "3"}


def test_field_values_can_be_cleared(temp_db):
    canvases = temp_db["canvases"]
    c = canvases.create_canvas("p", field_values={"a": "1"})
    canvases.update_canvas(c["canvas"]["id"], field_values={})
    got = canvases.get_canvas(c["canvas"]["id"])
    assert got["canvas"]["field_values"] == {}


def test_extract_tokens_helper(temp_db):
    from editor.app.canvases import extract_tokens
    prog = "tx,3.5,{{drawing_no}}; tx,4.5,{{revision}}; tx,5.5,{{drawing_no}};"
    # distinct + first-seen order
    assert extract_tokens(prog) == ["drawing_no", "revision"]


# ----- API-endpoint tests: use the shared app / production DB (like
# test_tagged_render.py) and clean up their own frames.

def _api_client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_frame_tokens_endpoint_declared_and_undeclared():
    from app import frames as frames_mod
    fid = "__v076_ftok"
    try:
        frames_mod.delete_frame(fid)
    except Exception:
        pass
    frames_mod.create_frame(
        frame_id=fid,
        name=fid,
        drawlang="tx,1,1,{{drawing_no}};tx,1,2,{{revision}};tx,1,3,{{new_token}};",
        fields=[
            {"name": "drawing_no", "default": "D-001", "label": "Drawing #", "editable": True, "line_index": 0},
            {"name": "revision", "default": "A", "label": "Rev", "editable": True, "line_index": 1},
        ],
    )
    try:
        with _api_client() as client:
            r = client.get(f"/api/frames/{fid}/tokens")
            assert r.status_code == 200
            d = r.json()
            assert d["tokens"] == ["drawing_no", "revision", "new_token"]
            assert d["declared"] == ["drawing_no", "revision"]
            assert d["undeclared"] == ["new_token"]
    finally:
        try:
            frames_mod.delete_frame(fid)
        except Exception:
            pass


def test_frame_tokens_endpoint_404_on_missing():
    with _api_client() as client:
        r = client.get("/api/frames/__v076_does_not_exist/tokens")
        assert r.status_code == 404


def test_frame_raw_endpoint_returns_all_fields():
    """GET /api/frames/{id}/raw exposes non-editable fields too."""
    from app import frames as frames_mod
    fid = "__v076_raw"
    try:
        frames_mod.delete_frame(fid)
    except Exception:
        pass
    frames_mod.create_frame(
        frame_id=fid,
        name=fid,
        drawlang="tx,1,1,{{a}};tx,1,2,{{b}};",
        fields=[
            {"name": "a", "default": "A", "editable": True, "line_index": 0},
            {"name": "b", "default": "B", "editable": False, "line_index": 1},
        ],
    )
    try:
        with _api_client() as client:
            r = client.get(f"/api/frames/{fid}/raw")
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["id"] == fid
            assert d["drawlang"].startswith("tx,1,1,{{a}}")
            names = [f["name"] for f in d["fields"]]
            assert names == ["a", "b"]  # both, editable and non-editable
            r2 = client.get("/api/frames/__v076_raw_missing/raw")
            assert r2.status_code == 404
    finally:
        try:
            frames_mod.delete_frame(fid)
        except Exception:
            pass


def test_program_substitutes_frame_tokens_from_field_values(temp_db):
    canvases = temp_db["canvases"]
    frames = temp_db["frames"]
    frames.create_frame(
        frame_id="ftitle",
        name="ftitle",
        drawlang="tx,10,10,{{drawing_no}};tx,10,20,{{revision}};",
        fields=[
            {"name": "drawing_no", "default": "D-999", "editable": True, "line_index": 0},
            {"name": "revision", "default": "A", "editable": True, "line_index": 1},
        ],
    )
    c = canvases.create_canvas(
        "instance",
        frame_id="ftitle",
        field_values={"drawing_no": "PA-001"},  # override; revision uses default
    )
    prog = canvases.get_canvas_program(c["canvas"]["id"])
    assert "{{drawing_no}}" not in prog
    assert "{{revision}}" not in prog
    assert "PA-001" in prog
    assert "A" in prog  # default fallback


def test_program_leaves_unknown_tokens_in_place(temp_db):
    canvases = temp_db["canvases"]
    frames = temp_db["frames"]
    frames.create_frame(
        frame_id="fpartial",
        name="fpartial",
        drawlang="tx,1,1,{{a}};tx,1,2,{{b}};",
        fields=[{"name": "a", "default": "", "editable": True, "line_index": 0}],  # b not declared
    )
    c = canvases.create_canvas(
        "inst",
        frame_id="fpartial",
        field_values={"a": "X"},
    )
    prog = canvases.get_canvas_program(c["canvas"]["id"])
    assert "X" in prog
    assert "{{b}}" in prog  # unresolved token stays visible


def test_body_drawlang_is_not_substituted(temp_db):
    """Body statements must never be touched by token substitution."""
    canvases = temp_db["canvases"]
    frames = temp_db["frames"]
    frames.create_frame(
        frame_id="fbody",
        name="fbody",
        drawlang="tx,1,1,{{title}};",
        fields=[{"name": "title", "default": "T", "editable": True, "line_index": 0}],
    )
    # Body drawlang contains a literal that *looks* like a token but must stay.
    c = canvases.create_canvas(
        "b",
        frame_id="fbody",
        program="tx,20,20,{{keep_me}};",
        field_values={"title": "Real Title"},
    )
    prog = canvases.get_canvas_program(c["canvas"]["id"])
    assert "Real Title" in prog
    assert "{{keep_me}}" in prog  # untouched


def test_api_canvases_post_and_patch_field_values():
    with _api_client() as client:
        r = client.post("/api/canvases", json={
            "name": "__v076_via_api",
            "field_values": {"drawing_no": "PA-042"},
        })
        assert r.status_code == 200, r.text
        data = r.json()
        cid = data["canvas"]["id"]
        try:
            assert data["canvas"]["field_values"] == {"drawing_no": "PA-042"}
            r2 = client.patch(f"/api/canvases/{cid}", json={
                "field_values": {"drawing_no": "PA-042", "revision": "B"}
            })
            assert r2.status_code == 200
            r3 = client.get(f"/api/canvases/{cid}").json()
            assert r3["canvas"]["field_values"] == {"drawing_no": "PA-042", "revision": "B"}
        finally:
            client.delete(f"/api/canvases/{cid}")
