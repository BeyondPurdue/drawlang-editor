"""Tests for the primitive catalog + expander."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# main.py uses bare ``from app import ...`` imports, so ``editor/`` must be
# on sys.path before we import it. This mirrors how the app is launched
# in production (uvicorn is started from the ``editor`` directory).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "editor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "editor"))

from editor.app import primitives  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


def test_catalog_dir_exists_and_has_json():
    d = primitives._catalog_dir()
    assert d.exists() and d.is_dir()
    files = sorted(d.glob("*.json"))
    assert len(files) >= 8, f"expected 8+ seed primitives, found {len(files)}"


def test_list_primitives_shape():
    rows = primitives.list_primitives()
    assert isinstance(rows, list) and rows
    row = rows[0]
    for key in ("id", "name", "category", "description", "params"):
        assert key in row
    # No template leaks into the light payload
    assert "template" not in row
    assert "template_variants" not in row


def test_all_seed_primitives_are_valid_json():
    d = primitives._catalog_dir()
    for path in d.glob("*.json"):
        data = json.loads(path.read_text())
        assert data["id"] == path.stem, f"id mismatch in {path.name}"
        assert data.get("name")
        assert "template" in data or "template_variants" in data


def test_get_primitive_unknown_returns_none():
    assert primitives.get_primitive("does-not-exist") is None


def test_expand_rect_defaults():
    p = primitives.get_primitive("rect")
    drawlang, tag = primitives.expand(p, {})
    assert drawlang == "rt,100,60;"
    assert tag == "primitive:rect{w=100,h=60}"


def test_expand_rect_custom_values():
    p = primitives.get_primitive("rect")
    drawlang, tag = primitives.expand(p, {"w": 250, "h": 40})
    assert drawlang == "rt,250,40;"
    assert "w=250" in tag and "h=40" in tag


def test_expand_circle_missing_value_uses_default():
    p = primitives.get_primitive("circle")
    drawlang, tag = primitives.expand(p, {"r": None})
    assert drawlang == "ci,20;"
    assert tag == "primitive:circle{r=20}"


def test_expand_label_text_arg_survives():
    p = primitives.get_primitive("label")
    drawlang, tag = primitives.expand(p, {"size": 14, "text": "Motor 101"})
    assert drawlang == "tx,14,Motor 101;"


def test_expand_terminal_uses_compute_block():
    p = primitives.get_primitive("terminal")
    drawlang, tag = primitives.expand(p, {"w": 60, "h": 20, "size": 10, "name": "T1"})
    # Template is three statements; each ends with ;
    stmts = [s.strip() for s in drawlang.split("\n") if s.strip()]
    assert stmts[0] == "rt,60,20;"
    assert stmts[2] == "tx,10,T1;"
    # compute'd label_x/label_y must have been numeric-substituted
    assert "{{" not in drawlang and "}}" not in drawlang


def test_expand_connector_l_variant_selection():
    p = primitives.get_primitive("connector_l")
    dl_h, _ = primitives.expand(p, {"dx": 80, "dy": 40, "order": "h-then-v"})
    dl_v, _ = primitives.expand(p, {"dx": 80, "dy": 40, "order": "v-then-h"})
    # Different variants must produce different drawlang
    assert dl_h != dl_v
    assert dl_h.startswith("dl,80,0;")
    assert dl_v.startswith("dl,0,40;")


def test_expand_arrow_uses_negative_compute():
    p = primitives.get_primitive("arrow")
    drawlang, _ = primitives.expand(p, {"length": 60, "head": 8})
    # arrow shaft first
    assert drawlang.split("\n")[0].strip() == "dl,60,0;"
    # a negative head_x should appear somewhere
    assert "-8" in drawlang


def test_expand_unknown_placeholder_raises():
    # Craft an invalid primitive on the fly
    bad = {
        "id": "bad",
        "name": "Bad",
        "params": [],
        "template": "rt,{{missing}},0;",
    }
    with pytest.raises(ValueError):
        primitives.expand(bad, {})


def test_safe_eval_rejects_dangerous_calls():
    with pytest.raises(ValueError):
        primitives._safe_eval("__import__('os').system('rm -rf /')", {})


def test_safe_eval_arithmetic():
    env = {"w": 100, "h": 60}
    assert primitives._safe_eval("w / 2", env) == 50
    assert primitives._safe_eval("h - 4", env) == 56
    assert primitives._safe_eval("max(w, h)", env) == 100


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


def test_api_list_primitives():
    r = client.get("/api/primitives")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    ids = {p["id"] for p in data["primitives"]}
    for expected in ("rect", "circle", "label", "terminal", "port",
                     "router_symbol", "connector_l", "arrow"):
        assert expected in ids, f"seed primitive missing from API: {expected}"


def test_api_get_primitive():
    r = client.get("/api/primitives/rect")
    assert r.status_code == 200
    p = r.json()["primitive"]
    assert p["id"] == "rect"
    assert "template" in p


def test_api_get_primitive_not_found():
    r = client.get("/api/primitives/nope")
    assert r.status_code == 404


def test_api_expand_rect():
    r = client.post("/api/primitives/rect/expand", json={"values": {"w": 200, "h": 80}})
    assert r.status_code == 200
    data = r.json()
    assert data["drawlang"] == "rt,200,80;"
    assert data["meaning_tag"].startswith("primitive:rect")


def test_api_expand_defaults_when_empty():
    r = client.post("/api/primitives/circle/expand", json={"values": {}})
    assert r.status_code == 200
    assert r.json()["drawlang"] == "ci,20;"


def test_api_expand_bad_primitive_400_or_404():
    r = client.post("/api/primitives/does-not-exist/expand", json={"values": {}})
    assert r.status_code == 404
