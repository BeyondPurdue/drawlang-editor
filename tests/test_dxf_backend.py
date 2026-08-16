"""
DXF backend — smoke and structural tests.

Verifies the AutoCAD 2000 (AC1015) ASCII DXF output for the v0.6 opcodes
that map onto CAD primitives. Full CAD-side rendering is out of scope
for pytest; instead we test:

  1. Every DXF file has HEADER, TABLES (LTYPE, LAYER, STYLE), and ENTITIES
     sections plus a final EOF.
  2. Every DXF file declares AC1015 and mm units.
  3. dl / dh / dv emit LINE with coordinates preserved (no y-flip).
  4. ci emits CIRCLE; rt emits a closed LWPOLYLINE.
  5. arc emits ARC with correct start / end (positive sweep passes through).
  6. tx emits TEXT with rotation, height, and string.
  7. Coloured entities land on the correct DL_<name> layer with the right
     AutoCAD Color Index.
  8. Dashed entities land on the DL_<name>_DASHED layer, linked to a
     DASHED linetype defined in the LTYPE table.
  9. EXTMIN / EXTMAX match the bounding box of the geometry.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drawlang import render  # noqa: E402


def _pairs(dxf: str):
    """Split a DXF string into (group_code:int, value:str) pairs."""
    lines = dxf.splitlines()
    out = []
    it = iter(lines)
    for a in it:
        try:
            b = next(it)
        except StopIteration:
            break
        code = a.strip()
        if not code.lstrip("-").isdigit():
            continue
        out.append((int(code), b))
    return out


def _entities_of(dxf: str, entity_name: str):
    """Return a list of dicts of group_code -> [values] for every entity
    of the given name in the ENTITIES section."""
    pairs = _pairs(dxf)
    # Trim to the ENTITIES section.
    in_entities = False
    section_pairs = []
    for code, val in pairs:
        if code == 0 and val == "SECTION":
            continue
        if code == 2 and val == "ENTITIES":
            in_entities = True
            continue
        if in_entities and code == 0 and val == "ENDSEC":
            break
        if in_entities:
            section_pairs.append((code, val))
    # Group by entity.
    ents = []
    current = None
    for code, val in section_pairs:
        if code == 0:
            if current is not None:
                ents.append(current)
            current = {"__type__": val}
        else:
            if current is None:
                continue
            current.setdefault(code, []).append(val)
    if current is not None:
        ents.append(current)
    return [e for e in ents if e["__type__"] == entity_name]


def test_dxf_has_required_sections():
    dxf = render("dl,10,0;", backend="dxf")
    assert "AC1015" in dxf, "must declare AutoCAD 2000 version"
    assert "$INSUNITS" in dxf, "must declare units"
    assert "\n4\n" in dxf, "INSUNITS value 4 (mm) must be present"
    assert "SECTION\n2\nHEADER" in dxf
    assert "SECTION\n2\nTABLES" in dxf
    assert "SECTION\n2\nENTITIES" in dxf
    assert dxf.rstrip().endswith("EOF")


def test_line_maps_to_LINE_with_correct_coords():
    # dl,10,0 draws a line from (0,0) to (10,0)
    dxf = render("dl,10,0;", backend="dxf")
    lines = _entities_of(dxf, "LINE")
    assert len(lines) == 1
    ln = lines[0]
    assert ln[10] == ["0"]      # x1 = 0
    assert ln[20] == ["0"]      # y1 = 0
    assert ln[11] == ["10"]     # x2 = 10
    assert ln[21] == ["0"]      # y2 = 0 (NO y-flip — DXF is y-up)


def test_circle_maps_to_CIRCLE():
    dxf = render("ci,5;", backend="dxf")
    circles = _entities_of(dxf, "CIRCLE")
    assert len(circles) == 1
    c = circles[0]
    assert c[10] == ["0"] and c[20] == ["0"]
    assert c[40] == ["5"]


def test_rectangle_maps_to_closed_LWPOLYLINE():
    # rt,W,H draws a rectangle at pen origin extending +W,+H
    dxf = render("rt,20,10;", backend="dxf")
    plines = _entities_of(dxf, "LWPOLYLINE")
    assert len(plines) == 1
    p = plines[0]
    assert p[90] == ["4"], "rectangle should have 4 vertices"
    assert p[70] == ["1"], "rectangle polyline must be closed"


def test_arc_maps_to_ARC_positive_sweep():
    # A quarter arc: opcode 'ar', radius=10, start=0, sweep=90 -> DXF ARC start=0 end=90
    dxf = render("mr,0,0;ar,10,0,90;", backend="dxf")
    arcs = _entities_of(dxf, "ARC")
    assert len(arcs) == 1
    a = arcs[0]
    assert a[40] == ["10"], "radius should be preserved"
    # DXF stores angles in degrees; start=0 end=90 for CCW quarter.
    assert float(a[50][0]) == 0.0
    assert float(a[51][0]) == 90.0


def test_text_maps_to_TEXT_with_content_and_size():
    # spec: tx,angle,string; pen.text_size set via ts.
    dxf = render('tz,3;tx,0,"Hello";', backend="dxf")
    texts = _entities_of(dxf, "TEXT")
    assert len(texts) == 1
    t = texts[0]
    # Parser passes the quoted literal through as-is (double quotes included);
    # this matches SVG/PS backend behaviour and is not the DXF backend's job to change.
    assert t[1] == ['"Hello"'], "text string must be preserved (with source quotes)"
    assert t[40] == ["3"], "text height must be preserved"
    assert t[50] == ["0"], "text rotation must be 0"
    # Text uses ISOCPEUR style by default.
    assert t[7] == ["ISOCPEUR"]


def test_color_modifier_selects_correct_layer_and_ACI():
    # ,c2 = red on the default palette -> layer DL_RED, ACI 1
    dxf = render("dl,10,0,c2;", backend="dxf")
    lines = _entities_of(dxf, "LINE")
    assert lines[0][8] == ["DL_RED"]
    # Confirm the LAYER table entry maps DL_RED to ACI 1.
    m = re.search(r"LAYER\n2\nDL_RED\n70\n0\n62\n(\d+)\n", dxf)
    assert m and m.group(1) == "1", "DL_RED must have ACI 1"


def test_dashed_modifier_uses_DASHED_variant_layer():
    dxf = render("dl,10,0,d;", backend="dxf")
    lines = _entities_of(dxf, "LINE")
    assert lines[0][8] == ["DL_INK_DASHED"]
    # DASHED linetype must be defined in the LTYPE table.
    assert re.search(r"LTYPE\n2\nDASHED\n", dxf), "DASHED linetype must be defined"
    # And the DL_INK_DASHED layer must reference it.
    m = re.search(r"LAYER\n2\nDL_INK_DASHED\n70\n0\n62\n\d+\n6\nDASHED\n", dxf)
    assert m, "DL_INK_DASHED must be bound to the DASHED linetype"


def test_extents_match_bounding_box_of_geometry():
    # A single 10x5 line from (0,0) to (10,5) should give EXTMIN 0,0 and
    # EXTMAX 10,5.
    dxf = render("dl,10,5;", backend="dxf")
    m_min = re.search(r"\$EXTMIN\n10\n([\-\d.]+)\n20\n([\-\d.]+)\n", dxf)
    m_max = re.search(r"\$EXTMAX\n10\n([\-\d.]+)\n20\n([\-\d.]+)\n", dxf)
    assert m_min and m_max
    assert float(m_min.group(1)) == 0.0
    assert float(m_min.group(2)) == 0.0
    assert float(m_max.group(1)) == 10.0
    assert float(m_max.group(2)) == 5.0


def test_invisible_line_emits_no_LINE_entity():
    dxf = render("dl,10,0,i;", backend="dxf")
    assert _entities_of(dxf, "LINE") == []


def test_render_dispatch_recognises_dxf():
    # Guard: the render() convenience entry point must accept 'dxf'.
    out = render("dl,1,0;", backend="dxf")
    assert isinstance(out, str)
    assert "AC1015" in out
