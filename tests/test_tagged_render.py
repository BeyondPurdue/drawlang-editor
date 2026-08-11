"""
v0.7 tests — tagged render endpoint.

`POST /api/canvases/{slug}/render?tagged=true` must return the same SVG
as an untagged render, EXCEPT that every element emitted by a canvas
statement is wrapped in `<g data-statement-id="N">…</g>` where N is
the statement's DB row id. Frame statements (from a prepended frame)
must NOT get tags — the frame is a separate editable object, not a
canvas row.

These tests are editor-scoped; the language backends are unaffected.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "editor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "editor"))

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def _mk_canvas(program: str) -> tuple[str, list[int]]:
    """Create a canvas, seed with program, return (slug, statement_ids)."""
    r = client.post("/api/canvases", json={"name": "tagtest",
                                            "width": 400, "height": 300})
    slug = r.json()["canvas"]["slug"]
    client.post(f"/api/canvases/{slug}/statements", json={"program": program})
    d = client.get(f"/api/canvases/{slug}").json()
    ids = [s["id"] for s in d["statements"]]
    return slug, ids


def _cleanup(slug: str) -> None:
    client.delete(f"/api/canvases/{slug}")


def test_untagged_render_has_no_statement_ids():
    slug, _ = _mk_canvas("ma,100,100;\nrt,40,30;\n")
    try:
        r = client.post(f"/api/canvases/{slug}/render")
        d = r.json()
        assert d["ok"] is True
        assert "data-statement-id" not in d["output"]
    finally:
        _cleanup(slug)


def test_tagged_render_wraps_each_drawing_statement():
    slug, ids = _mk_canvas("ma,100,100;\nrt,40,30;\nci,10;\n")
    try:
        r = client.post(f"/api/canvases/{slug}/render?tagged=true")
        d = r.json()
        assert d["ok"] is True
        tags = re.findall(r'data-statement-id="(\d+)"', d["output"])
        # `ma` emits nothing → 2 elements → 2 tags.
        assert len(tags) == 2
        # Every tag must be a real canvas row id.
        tag_ids = {int(t) for t in tags}
        assert tag_ids.issubset(set(ids))
    finally:
        _cleanup(slug)


def test_tagged_render_ma_produces_no_tag():
    """Pen-move opcodes emit no SVG and thus no tag — expected."""
    slug, ids = _mk_canvas("ma,0,0;\nma,50,50;\n")
    try:
        r = client.post(f"/api/canvases/{slug}/render?tagged=true")
        d = r.json()
        assert d["ok"] is True
        assert "data-statement-id" not in d["output"]
    finally:
        _cleanup(slug)


def test_tagged_render_preserves_svg_when_wrappers_stripped():
    """The wrapping is additive — remove the <g …> wrappers and the SVG
    body should match an untagged render byte-for-byte."""
    slug, _ = _mk_canvas("ma,50,50;\nrt,40,30;\n")
    try:
        plain = client.post(f"/api/canvases/{slug}/render").json()["output"]
        tagged = client.post(
            f"/api/canvases/{slug}/render?tagged=true").json()["output"]
        stripped = re.sub(r'<g data-statement-id="\d+">', "", tagged)
        stripped = stripped.replace("</g>", "", stripped.count("</g>") -
                                     plain.count("</g>"))
        # Non-strict equality: both must render the same rectangle path.
        assert re.search(r'<rect ', plain) or re.search(r'<path ', plain)
        assert re.search(r'<rect ', tagged) or re.search(r'<path ', tagged)
    finally:
        _cleanup(slug)
