"""
PostScript backend for the Drawing Language v0.1.

PostScript uses y-up coordinates natively — matches the language (spec §4.1).
No coordinate flip needed. This backend emits a self-contained EPS-compatible
PostScript document. `ps2pdf` (Ghostscript) converts it losslessly to PDF.

Emission strategy:

- One `newpath`/`stroke` (or `fill`) pair per drawing statement, so each
  visible mark maps to a clean, greppable block of PostScript.
- Color state is set via `setrgbcolor` immediately before drawing when a
  color modifier is present; PostScript's own color state is otherwise
  unchanged (defaults to black).
- Dashed lines are handled with `setdash`; state is reset with `[] 0 setdash`
  after every dashed statement so subsequent statements are solid unless they
  request dashing themselves.
"""

from __future__ import annotations

import math

DEFAULT_PALETTE = {
    0: (0.0, 0.0, 0.0),      # black
    1: (0.78, 0.16, 0.16),   # red
    2: (0.08, 0.40, 0.75),   # blue
    3: (0.18, 0.49, 0.20),   # green
    4: (0.98, 0.66, 0.15),   # gold
    5: (0.42, 0.11, 0.60),   # purple
    6: (0.31, 0.20, 0.18),   # brown
    7: (0.33, 0.43, 0.48),   # slate
}


class PostScriptBackend:
    """
    PostScript output backend.

    Constructor arguments:
        width, height: page size in drawing units. Used for %%BoundingBox.
                       If None, a bounding box is accumulated from content.
        stroke_width: default stroke width in drawing units.
        font_name: PostScript font (default "Helvetica").
        palette: dict mapping color index (int) to (r,g,b) tuples with each
                 component in [0.0, 1.0].
    """

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        stroke_width: float = 1.0,
        font_name: str = "Helvetica",
        palette: dict[int, tuple[float, float, float]] | None = None,
    ):
        self.width = width
        self.height = height
        self.stroke_width = stroke_width
        self.font_name = font_name
        self.palette = dict(DEFAULT_PALETTE)
        if palette:
            self.palette.update(palette)
        self._body_parts: list[str] = []
        self._bbox: list[float] | None = None

    # -- Backend interface ---------------------------------------------------

    def draw_line(self, x1, y1, x2, y2, mods):
        self._track_bbox([(x1, y1), (x2, y2)])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        self._emit_dash(mods)
        self._body_parts.append(
            f"newpath {x1} {y1} moveto {x2} {y2} lineto stroke"
        )
        self._reset_dash(mods)

    def draw_rectangle(self, x, y, w, h, mods):
        x0 = x if w >= 0 else x + w
        y0 = y if h >= 0 else y + h
        w0 = abs(w)
        h0 = abs(h)
        self._track_bbox([(x0, y0), (x0 + w0, y0 + h0)])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        self._emit_dash(mods)
        if mods["fill"]:
            self._body_parts.append(f"newpath {x0} {y0} {w0} {h0} rectfill")
        else:
            self._body_parts.append(f"newpath {x0} {y0} {w0} {h0} rectstroke")
        self._reset_dash(mods)

    def draw_circle(self, cx, cy, r, mods):
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        self._emit_dash(mods)
        op = "fill" if mods["fill"] else "stroke"
        self._body_parts.append(
            f"newpath {cx} {cy} {r} 0 360 arc {op}"
        )
        self._reset_dash(mods)

    def draw_arc(self, cx, cy, r, start_angle, sweep_angle, mods):
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        self._emit_dash(mods)
        # PostScript `arc` goes counterclockwise from start_angle to end_angle;
        # `arcn` goes clockwise. In language space, positive sweep = CCW.
        end_angle = start_angle + sweep_angle
        if sweep_angle >= 0:
            arc_cmd = f"{cx} {cy} {r} {start_angle} {end_angle} arc"
        else:
            arc_cmd = f"{cx} {cy} {r} {start_angle} {end_angle} arcn"

        if mods["fill"]:
            # Filled pie slice: newpath, move to center, arc, close, fill
            self._body_parts.append(
                f"newpath {cx} {cy} moveto {arc_cmd} closepath fill"
            )
        else:
            self._body_parts.append(f"newpath {arc_cmd} stroke")
        self._reset_dash(mods)

    def draw_bezier(self, p0, p1, p2, p3, mods):
        self._track_bbox([p0, p1, p2, p3])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        self._emit_dash(mods)
        self._body_parts.append(
            f"newpath {p0[0]} {p0[1]} moveto "
            f"{p1[0]} {p1[1]} {p2[0]} {p2[1]} {p3[0]} {p3[1]} curveto stroke"
        )
        self._reset_dash(mods)

    def draw_text(self, x, y, size, angle, text, mods):
        self._track_bbox([(x, y), (x + size * max(1, len(text)) * 0.6, y + size)])
        if mods["invisible"]:
            return
        self._emit_color(mods)
        # PostScript rotate is CCW positive — matches language convention.
        escaped = _escape_ps_string(text)
        self._body_parts.append(
            f"gsave "
            f"/{self.font_name} findfont {size} scalefont setfont "
            f"{x} {y} moveto "
            f"{angle} rotate "
            f"({escaped}) show "
            f"grestore"
        )

    def place_image(self, x, y, w, h, image_id):
        # PostScript image rendering requires the actual image data. For v0.1
        # we emit a comment marker; a later pass can splice in the raster.
        self._track_bbox([(x, y), (x + w, y + h)])
        self._body_parts.append(
            f"% [IMAGE PLACEHOLDER image_id={image_id} at {x},{y} size {w}x{h}]"
        )

    def finalize(self) -> str:
        if self.width is not None and self.height is not None:
            bb = f"0 0 {self.width} {self.height}"
            page_w = self.width
            page_h = self.height
        elif self._bbox is not None:
            xmin, ymin, xmax, ymax = self._bbox
            pad = 5
            bb = f"{int(xmin - pad)} {int(ymin - pad)} {int(xmax + pad)} {int(ymax + pad)}"
            page_w = int(xmax - xmin + 2 * pad)
            page_h = int(ymax - ymin + 2 * pad)
        else:
            bb = "0 0 100 100"
            page_w, page_h = 100, 100

        body = "\n".join(self._body_parts)
        return (
            f"%!PS-Adobe-3.0 EPSF-3.0\n"
            f"%%BoundingBox: {bb}\n"
            f"%%Title: Drawing Language v0.1 output\n"
            f"%%Creator: drawlang.ps_backend\n"
            f"%%EndComments\n"
            f"gsave\n"
            f"{self.stroke_width} setlinewidth\n"
            f"1 setlinejoin 1 setlinecap\n"
            f"{body}\n"
            f"grestore\n"
            f"showpage\n"
            f"%%EOF\n"
        )

    # -- Internals -----------------------------------------------------------

    def _emit_color(self, mods):
        idx = mods.get("color") or 0
        r, g, b = self.palette.get(idx, self.palette[0])
        self._body_parts.append(f"{r:.3f} {g:.3f} {b:.3f} setrgbcolor")

    def _emit_dash(self, mods):
        if mods["dashed"]:
            self._body_parts.append("[4 4] 0 setdash")

    def _reset_dash(self, mods):
        if mods["dashed"]:
            self._body_parts.append("[] 0 setdash")

    def _track_bbox(self, pts):
        for x, y in pts:
            if self._bbox is None:
                self._bbox = [float(x), float(y), float(x), float(y)]
            else:
                self._bbox[0] = min(self._bbox[0], x)
                self._bbox[1] = min(self._bbox[1], y)
                self._bbox[2] = max(self._bbox[2], x)
                self._bbox[3] = max(self._bbox[3], y)


def _escape_ps_string(text: str) -> str:
    """Escape PostScript literal-string special characters."""
    return (
        text.replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )
