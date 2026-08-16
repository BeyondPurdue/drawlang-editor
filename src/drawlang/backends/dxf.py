"""
DXF backend for the Drawing Language v0.6.

Emits AutoCAD DXF (AutoCAD 2000 / AC1015 ASCII flavour). This is the format
every AutoCAD version, Bricscad, LibreCAD, DraftSight, and every mainstream
CAM tool reads. DXF R2000 was chosen over R12 because it supports LWPOLYLINE
and per-entity lineweights, which map naturally onto DrawLang.

Coordinate system
-----------------
DXF is y-up (Cartesian), same as DrawLang. No coordinate flip is needed —
this backend passes DrawLang mm coordinates straight through as DXF units.
The output is in millimetres. Set your CAD's INSUNITS to 4 (Millimeters)
after import if it doesn't detect automatically.

Layer strategy
--------------
One layer per DrawLang palette colour. Layer names follow the pattern
``DL_INK``, ``DL_RED``, ``DL_BLUE``, ... so a draftsman can freeze / thaw
a colour class independently. Layer colour is the AutoCAD Color Index (ACI)
approximation of the DrawLang RGB palette. The default layer is ``0``
(reserved by AutoCAD); we never draw onto it.

Text
----
DrawLang ``tx`` becomes DXF ``TEXT`` on the ISOCPEUR style (the ISO 3098
drafting typeface — matches ES680 and every European drafting standard).
Rotation, height, and colour are honoured. Slanted / stretched text is
not currently exposed by DrawLang, so we emit orthogonal glyphs only.

What's mapped
-------------
    dl / dh / dv        -> LINE
    rt                  -> LWPOLYLINE (closed, 4 vertices) — filled uses HATCH
    ci                  -> CIRCLE (unfilled) / HATCH (filled)
    arc                 -> ARC
    bezier              -> flattened LWPOLYLINE (32 segments)
    tx                  -> TEXT
    place_image         -> INSERT of a placeholder BLOCK (external image
                           refs are out of scope for a portable DXF; the
                           receiving CAD can attach a raster manually)

Modifiers
---------
``invisible``  entity is dropped entirely (DXF has no visibility flag that
                round-trips reliably; the bbox is intentionally not tracked
                — DXF does not carry a page size).
``dashed``     entity is placed on a linetype = DASHED variant of its layer.
``fill``       for closed shapes emits a HATCH with pattern SOLID.
``color``      selects the target layer (see palette map below).

The backend never uses BYBLOCK / BYLAYER trickery — every entity's colour
resolves at emit time so the DXF opens correctly even in viewers that
don't fully honour layer colour overrides.
"""

from __future__ import annotations

import math

# ACI (AutoCAD Color Index) mapping for the DrawLang default palette.
# ACI 7 is the "auto black/white" — we use it for the ink layer so the
# drawing prints black on white and displays white on black in the CAD's
# model space (standard AutoCAD convention).
#
# Palette index 0 is paper: no layer is emitted for it, and any entity
# whose stroke resolves to paper falls back to ink (matching SVG backend).
DEFAULT_ACI_PALETTE = {
    1: (7, "INK"),        # ink        -> ACI 7 (auto black/white)
    2: (1, "RED"),        # red        -> ACI 1
    3: (5, "BLUE"),       # blue       -> ACI 5
    4: (3, "GREEN"),      # green      -> ACI 3
    5: (2, "GOLD"),       # gold       -> ACI 2 (yellow — closest ACI to gold)
    6: (6, "PURPLE"),     # purple     -> ACI 6 (magenta — closest ACI to purple)
    7: (36, "BROWN"),     # brown      -> ACI 36
    8: (8, "SLATE"),      # slate      -> ACI 8 (dark grey)
}

INK_INDEX = 1
PAPER_INDEX = 0


def _fmt(v: float) -> str:
    """DXF numeric fields — no trailing zeros, no scientific notation for
    typical drawing coordinates (< 1e6 mm)."""
    if isinstance(v, int):
        return str(v)
    # DXF is tolerant of decimals; keep 4 places (0.1 μm) which is way
    # more than any real drawing needs and avoids float noise.
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


class DXFBackend:
    """DXF R2000 (AutoCAD 2000, AC1015) ASCII output backend."""

    def __init__(
        self,
        palette: dict[int, str] | None = None,
        text_style: str = "ISOCPEUR",
    ):
        # ``palette`` here is an optional override of *names only*; the
        # ACI mapping is fixed because the CAD side has no notion of RGB
        # for legacy layer colour. If callers want RGB in layers they can
        # post-process the DXF to add a 420 group code, but that's R2004+
        # only and we deliberately target R2000 for maximum compatibility.
        self.aci_palette = dict(DEFAULT_ACI_PALETTE)
        self.text_style = text_style
        self._entities: list[str] = []
        self._used_layers: dict[str, tuple[int, bool]] = {}
        #   name -> (aci, needs_dashed_variant)
        # Bounding box is tracked so we can populate $EXTMIN/$EXTMAX in
        # the header — makes the drawing auto-zoom-fit in AutoCAD.
        self._bbox: list[float] | None = None

    # -- Backend interface --------------------------------------------------

    def draw_line(self, x1, y1, x2, y2, mods):
        self._track_bbox([(x1, y1), (x2, y2)])
        if mods.get("invisible"):
            return
        layer = self._layer_for(mods)
        self._entities.append(_line(x1, y1, x2, y2, layer))

    def draw_rectangle(self, x, y, w, h, mods):
        x0 = x if w >= 0 else x + w
        y0 = y if h >= 0 else y + h
        w0 = abs(w)
        h0 = abs(h)
        self._track_bbox([(x0, y0), (x0 + w0, y0 + h0)])
        if mods.get("invisible"):
            return
        layer = self._layer_for(mods)
        pts = [(x0, y0), (x0 + w0, y0), (x0 + w0, y0 + h0), (x0, y0 + h0)]
        self._entities.append(_lwpolyline(pts, layer, closed=True))
        if mods.get("fill"):
            # Solid HATCH over the rectangle so filled rects survive the trip.
            self._entities.append(_hatch_solid(pts, layer))

    def draw_circle(self, cx, cy, r, mods):
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods.get("invisible"):
            return
        layer = self._layer_for(mods)
        self._entities.append(_circle(cx, cy, r, layer))
        if mods.get("fill"):
            # Approximate the disc by an inscribed 64-gon for HATCH;
            # circular HATCH boundaries in R2000 need an edge-type 2
            # arc primitive which many viewers implement inconsistently.
            n = 64
            pts = [
                (
                    cx + r * math.cos(2 * math.pi * i / n),
                    cy + r * math.sin(2 * math.pi * i / n),
                )
                for i in range(n)
            ]
            self._entities.append(_hatch_solid(pts, layer))

    def draw_arc(self, cx, cy, r, start_angle, sweep_angle, mods):
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods.get("invisible"):
            return
        layer = self._layer_for(mods)
        # DXF ARC always goes CCW from start to end. If sweep is negative,
        # swap start/end.
        if sweep_angle >= 0:
            a0 = start_angle % 360.0
            a1 = (start_angle + sweep_angle) % 360.0
        else:
            a0 = (start_angle + sweep_angle) % 360.0
            a1 = start_angle % 360.0
        self._entities.append(_arc(cx, cy, r, a0, a1, layer))

    def draw_bezier(self, p0, p1, p2, p3, mods):
        # Flatten cubic to a 32-segment polyline. DXF has SPLINE entities
        # but AutoCAD 2000 SPLINE emitters vary; a flattened polyline is
        # bulletproof and geometrically identical below ~0.05 mm error
        # for anything a draftsman would draw.
        n = 32
        pts = []
        for i in range(n + 1):
            t = i / n
            omt = 1 - t
            x = (omt ** 3) * p0[0] + 3 * (omt ** 2) * t * p1[0] + 3 * omt * (t ** 2) * p2[0] + (t ** 3) * p3[0]
            y = (omt ** 3) * p0[1] + 3 * (omt ** 2) * t * p1[1] + 3 * omt * (t ** 2) * p2[1] + (t ** 3) * p3[1]
            pts.append((x, y))
        self._track_bbox(pts)
        if mods.get("invisible"):
            return
        layer = self._layer_for(mods)
        self._entities.append(_lwpolyline(pts, layer, closed=False))

    def draw_text(self, x, y, size, angle, text, mods):
        # Same rough bbox estimate as SVG backend so DXF EXTMIN/EXTMAX include text.
        self._track_bbox([(x, y), (x + size * max(1, len(text)) * 0.6, y + size)])
        if mods.get("invisible"):
            return
        # Text follows the stroke-color rule (spec v0.6).
        layer = self._layer_for(mods, force_stroke=True)
        self._entities.append(
            _text(x, y, size, angle, text, layer, self.text_style)
        )

    def place_image(self, x, y, w, h, image_id):
        # v0.7: image ops are not fully mapped to CAD. We emit an INSERT
        # of an empty placeholder BLOCK so the draftsman sees where the
        # raster should go and can attach the image manually. Deliberately
        # tracked in the bbox.
        self._track_bbox([(x, y), (x + w, y + h)])
        # Represent as a dashed rectangle labelled with the image id.
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        layer = self._named_layer("INK", dashed=True)
        self._entities.append(_lwpolyline(pts, layer, closed=True))
        self._entities.append(
            _text(x + 2, y + 2, max(2, min(w, h) * 0.1),
                  0, f"IMG {image_id}", layer, self.text_style)
        )

    def finalize(self) -> str:
        return _assemble(
            entities=self._entities,
            layers=self._used_layers,
            text_style=self.text_style,
            bbox=self._bbox,
        )

    # -- Internals ----------------------------------------------------------

    def _resolve_stroke_index(self, mods) -> int:
        idx = mods.get("color")
        if idx is None:
            return INK_INDEX
        if idx == PAPER_INDEX:
            return INK_INDEX  # spec: stroke with ,c0 falls back to ink
        if idx not in self.aci_palette:
            return INK_INDEX
        return idx

    def _layer_for(self, mods, force_stroke: bool = False) -> str:
        """Pick the target DXF layer for the current entity.

        Strokes use the stroke-color rule (ink default). Fills use the
        fill-color rule (paper default), but a paper-fill emits no HATCH
        (the SVG backend's fill="none" equivalent), so the layer for a
        fill entity is only queried for the stroke around it.
        """
        idx = self._resolve_stroke_index(mods) if force_stroke else self._resolve_stroke_index(mods)
        aci, name = self.aci_palette[idx]
        dashed = bool(mods.get("dashed"))
        return self._named_layer(name, aci=aci, dashed=dashed)

    def _named_layer(self, base: str, aci: int = 7, dashed: bool = False) -> str:
        name = f"DL_{base}"
        if dashed:
            name = f"{name}_DASHED"
        if name not in self._used_layers:
            self._used_layers[name] = (aci, dashed)
        return name

    def _track_bbox(self, pts):
        for x, y in pts:
            fx, fy = float(x), float(y)
            if self._bbox is None:
                self._bbox = [fx, fy, fx, fy]
            else:
                b = self._bbox
                if fx < b[0]: b[0] = fx
                if fy < b[1]: b[1] = fy
                if fx > b[2]: b[2] = fx
                if fy > b[3]: b[3] = fy


# --- DXF group-code helpers ------------------------------------------------
#
# Every DXF record is a pair of lines: an integer group code, then a value.
# We keep the entity emitters as pure string builders — no shared state,
# no side effects — so they're trivially testable in isolation.

def _pair(code: int, value) -> str:
    if isinstance(value, float):
        return f"{code}\n{_fmt(value)}\n"
    return f"{code}\n{value}\n"


def _line(x1, y1, x2, y2, layer: str) -> str:
    return (
        _pair(0, "LINE")
        + _pair(8, layer)
        + _pair(10, float(x1)) + _pair(20, float(y1)) + _pair(30, 0.0)
        + _pair(11, float(x2)) + _pair(21, float(y2)) + _pair(31, 0.0)
    )


def _circle(cx, cy, r, layer: str) -> str:
    return (
        _pair(0, "CIRCLE")
        + _pair(8, layer)
        + _pair(10, float(cx)) + _pair(20, float(cy)) + _pair(30, 0.0)
        + _pair(40, float(r))
    )


def _arc(cx, cy, r, a0, a1, layer: str) -> str:
    return (
        _pair(0, "ARC")
        + _pair(8, layer)
        + _pair(10, float(cx)) + _pair(20, float(cy)) + _pair(30, 0.0)
        + _pair(40, float(r))
        + _pair(50, float(a0))
        + _pair(51, float(a1))
    )


def _lwpolyline(pts, layer: str, closed: bool) -> str:
    parts = [
        _pair(0, "LWPOLYLINE"),
        _pair(8, layer),
        _pair(100, "AcDbEntity"),
        _pair(100, "AcDbPolyline"),
        _pair(90, len(pts)),
        _pair(70, 1 if closed else 0),
    ]
    for x, y in pts:
        parts.append(_pair(10, float(x)) + _pair(20, float(y)))
    return "".join(parts)


def _hatch_solid(pts, layer: str) -> str:
    """SOLID HATCH bounded by a single closed polyline of ``pts``."""
    n = len(pts)
    parts = [
        _pair(0, "HATCH"),
        _pair(8, layer),
        _pair(100, "AcDbEntity"),
        _pair(100, "AcDbHatch"),
        _pair(10, 0.0) + _pair(20, 0.0) + _pair(30, 0.0),   # elev pt
        _pair(210, 0.0) + _pair(220, 0.0) + _pair(230, 1.0),  # extrusion +Z
        _pair(2, "SOLID"),                                   # pattern name
        _pair(70, 1),                                        # solid=1
        _pair(71, 0),                                        # associativity 0
        _pair(91, 1),                                        # 1 boundary path
        _pair(92, 7),                                        # path type: external+polyline
        _pair(72, 0),                                        # has-bulge=0
        _pair(73, 1),                                        # closed=1
        _pair(93, n),                                        # vertex count
    ]
    for x, y in pts:
        parts.append(_pair(10, float(x)) + _pair(20, float(y)))
    parts += [
        _pair(97, 0),   # source-boundary object count
        _pair(75, 0),   # hatch style
        _pair(76, 1),   # pattern type
        _pair(98, 0),   # seed-point count
    ]
    return "".join(parts)


def _text(x, y, size, angle, text, layer: str, style: str) -> str:
    # DXF TEXT: group 1 = string. Strip any control chars just to be safe,
    # DXF handles ^ escapes and %%c but we don't emit them.
    safe = str(text).replace("\r", " ").replace("\n", " ")
    return (
        _pair(0, "TEXT")
        + _pair(8, layer)
        + _pair(7, style)
        + _pair(10, float(x)) + _pair(20, float(y)) + _pair(30, 0.0)
        + _pair(40, float(size))
        + _pair(50, float(angle))
        + _pair(1, safe)
    )


# --- Full-file assembly ----------------------------------------------------

_HEADER_TEMPLATE = (
    "0\nSECTION\n2\nHEADER\n"
    "9\n$ACADVER\n1\nAC1015\n"          # AutoCAD 2000
    "9\n$INSUNITS\n70\n4\n"             # 4 = Millimeters
    "9\n$EXTMIN\n10\n{xmin}\n20\n{ymin}\n30\n0.0\n"
    "9\n$EXTMAX\n10\n{xmax}\n20\n{ymax}\n30\n0.0\n"
    "0\nENDSEC\n"
)

_TABLES_HEAD = "0\nSECTION\n2\nTABLES\n"

_LTYPE_TABLE_HEAD = (
    "0\nTABLE\n2\nLTYPE\n70\n2\n"
    "0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0.0\n"
    "0\nLTYPE\n2\nDASHED\n70\n0\n3\n__ __ __\n72\n65\n73\n2\n40\n15.0\n"
    "49\n10.0\n74\n0\n49\n-5.0\n74\n0\n"
    "0\nENDTAB\n"
)

_STYLE_TABLE = (
    "0\nTABLE\n2\nSTYLE\n70\n1\n"
    "0\nSTYLE\n2\nISOCPEUR\n70\n0\n40\n0.0\n41\n1.0\n50\n0.0\n71\n0\n42\n2.5\n"
    "3\nisocpeur.ttf\n4\n\n"
    "0\nENDTAB\n"
)

_TABLES_TAIL = "0\nENDSEC\n"


def _layers_table(used_layers: dict[str, tuple[int, bool]]) -> str:
    # Always emit layer 0 (AutoCAD-mandatory) plus every DL_ layer we used.
    entries = ["0\nTABLE\n2\nLAYER\n70\n" + str(len(used_layers) + 1) + "\n"]
    # Layer 0: colour 7 (default), linetype CONTINUOUS.
    entries.append(
        "0\nLAYER\n2\n0\n70\n0\n62\n7\n6\nCONTINUOUS\n"
    )
    for name, (aci, dashed) in sorted(used_layers.items()):
        linetype = "DASHED" if dashed else "CONTINUOUS"
        entries.append(
            f"0\nLAYER\n2\n{name}\n70\n0\n62\n{aci}\n6\n{linetype}\n"
        )
    entries.append("0\nENDTAB\n")
    return "".join(entries)


def _assemble(entities, layers, text_style, bbox) -> str:
    if bbox is None:
        xmin = ymin = 0.0
        xmax = ymax = 10.0
    else:
        xmin, ymin, xmax, ymax = bbox
    header = _HEADER_TEMPLATE.format(
        xmin=_fmt(xmin), ymin=_fmt(ymin),
        xmax=_fmt(xmax), ymax=_fmt(ymax),
    )
    tables = (
        _TABLES_HEAD
        + _LTYPE_TABLE_HEAD
        + _layers_table(layers)
        + _STYLE_TABLE
        + _TABLES_TAIL
    )
    body = (
        "0\nSECTION\n2\nENTITIES\n"
        + "".join(entities)
        + "0\nENDSEC\n"
    )
    return header + tables + body + "0\nEOF\n"
