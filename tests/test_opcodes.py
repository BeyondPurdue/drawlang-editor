"""
v0.7 tests — opcode catalog served by /api/opcodes.

The catalog is the sole source of the Primitives tab. It must:
  - list all 7 core opcodes (spec §6) + 4 extension opcodes (§7),
  - name each argument with a spec-consistent short label,
  - reject unknown opcodes with 404,
  - never leak composed/invented shapes into the primitives set.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "editor") not in sys.path:
    sys.path.insert(0, str(_ROOT / "editor"))

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


# Spec-anchored expected sets. Update ONLY when the language spec adds or
# removes an opcode. Composed shapes must never appear here.
CORE = {"mr", "ma", "dl", "rt", "ci", "tx"}
EXTENSION = {"ar", "bz", "sp", "im"}


def test_list_returns_all_opcodes():
    r = client.get("/api/opcodes")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    opcodes = d["opcodes"]
    assert len(opcodes) == len(CORE) + len(EXTENSION)


def test_list_covers_full_core_and_extension_sets():
    r = client.get("/api/opcodes")
    d = r.json()
    present = {op["opcode"] for op in d["opcodes"]}
    assert present == CORE | EXTENSION


def test_each_opcode_has_required_metadata():
    r = client.get("/api/opcodes")
    for op in r.json()["opcodes"]:
        assert op["opcode"], f"missing opcode mnemonic on {op}"
        assert op["name"], f"missing name on {op['opcode']}"
        assert op["group"] in ("core", "extension"), op
        assert isinstance(op["args"], list) and len(op["args"]) >= 1
        for arg in op["args"]:
            assert "name" in arg and "type" in arg and "default" in arg


def test_core_opcodes_marked_core():
    r = client.get("/api/opcodes")
    for op in r.json()["opcodes"]:
        if op["opcode"] in CORE:
            assert op["group"] == "core", op


def test_extension_opcodes_marked_extension():
    r = client.get("/api/opcodes")
    for op in r.json()["opcodes"]:
        if op["opcode"] in EXTENSION:
            assert op["group"] == "extension", op


def test_get_single_opcode_returns_full_entry():
    r = client.get("/api/opcodes/rt")
    assert r.status_code == 200
    d = r.json()
    assert d["opcode"]["opcode"] == "rt"
    assert [a["name"] for a in d["opcode"]["args"]] == ["w", "h"]


def test_get_bezier_has_six_args():
    r = client.get("/api/opcodes/bz")
    d = r.json()
    args = d["opcode"]["args"]
    assert [a["name"] for a in args] == ["cx1", "cy1", "cx2", "cy2", "ex", "ey"]


def test_get_unknown_opcode_returns_404():
    r = client.get("/api/opcodes/zz")
    assert r.status_code == 404


def test_every_catalog_opcode_is_parser_accepted():
    """Regression: the catalog listed 'po'/'ra'/'da' but the parser only knew
    'sp'/'im'/(nothing). Placing a polyline crashed the editor. From now on
    every catalog mnemonic must round-trip through the actual parser.
    """
    from drawlang.parser import parse
    r = client.get("/api/opcodes").json()
    for op in r["opcodes"]:
        # Build a minimal statement using the declared default args.
        args = ",".join(str(a["default"]) for a in op["args"])
        src = f"{op['opcode']},{args};"
        # Should parse without a LexicalError.
        parse(src)


def test_primitives_tab_and_symbols_tab_are_separate():
    """Composed/invented shapes must NOT appear in the opcode catalog.

    Any 'router_symbol', 'terminal', 'arrow' etc. lives under /api/primitives
    (the parametric-symbol layer) and is exposed in the Symbols tab, never
    in Primitives. This guards against a future well-meaning contributor
    dumping them back into the opcode set.
    """
    r = client.get("/api/opcodes")
    codes = {op["opcode"] for op in r.json()["opcodes"]}
    forbidden = {"router_symbol", "terminal", "port", "arrow", "connector_l",
                 "rect", "circle", "label"}
    assert not (codes & forbidden), (
        f"invented shapes leaked into the opcode catalog: {codes & forbidden}"
    )
