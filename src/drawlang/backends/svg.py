"""
SVG backend for the Drawing Language v0.1.

The language uses a y-up Cartesian coordinate system (spec §4.1); SVG uses
y-down. This backend performs the y-flip in a single top-level <g transform>
so all drawing operations can emit language-space coordinates directly.

The backend does not attempt to match a physical unit — it outputs abstract
units and lets the consumer set `viewBox` + `width` + `height` to scale.
"""

from __future__ import annotations

import html
import math

# Default palette (spec v0.6).
#
# Palette index 0 is reserved as `paper` — the background / non-color slot.
# Fills that resolve to index 0 emit `fill="none"` in SVG (invisible fill).
# This matches the historical Siemens ES680 HMI, where palette entry 0 was
# the workstation background color, so `rt,W,H,f` with no explicit `,c<n>`
# drew a rectangle whose fill was the background (visually just the outline).
#
# Indices 1..7 are drawing colors. `ink` (index 1) is the default stroke and
# text color used when no explicit `,c<n>` is supplied. This asymmetry — no
# color means paper for fill but ink for stroke — is exactly what makes bare
# `rt,W,H,f` render as an outline rather than a solid black block.
#
# Real projects may override the palette via the SVGBackend constructor.
PAPER_INDEX = 0
INK_INDEX = 1
DEFAULT_PALETTE = {
    0: None,        # paper — sentinel for "no color" / background; renders as fill="none"
    1: "#000000",   # ink — default drawing color (stroke + text)
    2: "#c62828",   # red
    3: "#1565c0",   # blue
    4: "#2e7d32",   # green
    5: "#f9a825",   # gold
    6: "#6a1b9a",   # purple
    7: "#4e342e",   # brown
    8: "#546e7a",   # slate
}


class SVGBackend:
    """
    SVG output backend.

    Constructor arguments:
        width, height: viewport size in drawing units (used for viewBox).
                       If either is None the backend accumulates a bounding
                       box and sets viewBox to that plus a small padding.
        origin_x, origin_y: language-space origin (default (0,0)). Used to
                       shift the viewBox if the drawing content is offset.
        stroke_width: default stroke width in drawing units (default 1).
        font_family: font used for `tx` text (default "sans-serif").
        palette: dict mapping color index (int) to CSS color string.
    """

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        origin_x: int = 0,
        origin_y: int = 0,
        stroke_width: float = 1.0,
        font_family: str = "sans-serif",
        palette: dict[int, str] | None = None,
    ):
        self.width = width
        self.height = height
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.stroke_width = stroke_width
        self.font_family = font_family
        self.palette = dict(DEFAULT_PALETTE)
        if palette:
            self.palette.update(palette)
        self._body_parts: list[str] = []
        # Bounding-box accumulator, used when width/height are not fixed
        self._bbox: list[float] | None = None  # [xmin, ymin, xmax, ymax]

    # -- Backend interface ---------------------------------------------------

    def draw_line(self, x1, y1, x2, y2, mods):
        if mods["invisible"]:
            self._track_bbox([(x1, y1), (x2, y2)])
            return
        attrs = self._stroke_attrs(mods)
        self._body_parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {attrs} />'
        )
        self._track_bbox([(x1, y1), (x2, y2)])

    def draw_rectangle(self, x, y, w, h, mods):
        # Normalize so w,h positive and (x,y) is lower-left in language space.
        x0 = x if w >= 0 else x + w
        y0 = y if h >= 0 else y + h
        w0 = abs(w)
        h0 = abs(h)
        self._track_bbox([(x0, y0), (x0 + w0, y0 + h0)])
        if mods["invisible"]:
            return
        attrs = self._paint_attrs(mods)
        self._body_parts.append(
            f'<rect x="{x0}" y="{y0}" width="{w0}" height="{h0}" {attrs} />'
        )

    def draw_circle(self, cx, cy, r, mods):
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods["invisible"]:
            return
        attrs = self._paint_attrs(mods)
        self._body_parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" {attrs} />'
        )

    def draw_arc(self, cx, cy, r, start_angle, sweep_angle, mods):
        # Convert to endpoints in language space (y-up, CCW).
        a0 = math.radians(start_angle)
        a1 = math.radians(start_angle + sweep_angle)
        x0 = cx + r * math.cos(a0)
        y0 = cy + r * math.sin(a0)
        x1 = cx + r * math.cos(a1)
        y1 = cy + r * math.sin(a1)
        self._track_bbox([(cx - r, cy - r), (cx + r, cy + r)])
        if mods["invisible"]:
            return

        large_arc = 1 if abs(sweep_angle) > 180.0 else 0
        # SVG sweep-flag: 1 = CCW in y-DOWN, but we're inside a y-flip <g>.
        # In language space CCW == positive sweep_angle. After the y-flip <g>,
        # SVG sees the arc mirrored, so sweep_flag=1 corresponds to language-
        # space CCW. So: sweep_angle > 0 → sweep_flag = 1.
        sweep_flag = 1 if sweep_angle > 0 else 0

        attrs = self._paint_attrs(mods)
        if mods["fill"]:
            # Filled pie slice: move to center, line to arc start, arc, close
            d = (
                f"M {cx} {cy} L {x0} {y0} "
                f"A {r} {r} 0 {large_arc} {sweep_flag} {x1} {y1} Z"
            )
        else:
            d = f"M {x0} {y0} A {r} {r} 0 {large_arc} {sweep_flag} {x1} {y1}"
        self._body_parts.append(f'<path d="{d}" {attrs} />')

    def draw_bezier(self, p0, p1, p2, p3, mods):
        self._track_bbox([p0, p1, p2, p3])
        if mods["invisible"]:
            return
        attrs = self._paint_attrs(mods)
        d = (
            f"M {p0[0]} {p0[1]} "
            f"C {p1[0]} {p1[1]}, {p2[0]} {p2[1]}, {p3[0]} {p3[1]}"
        )
        self._body_parts.append(f'<path d="{d}" {attrs} />')

    def draw_text(self, x, y, size, angle, text, mods):
        self._track_bbox([(x, y), (x + size * max(1, len(text)) * 0.6, y + size)])
        if mods["invisible"]:
            return
        # v0.6: text follows the stroke-color rule — default is ink (palette 1),
        # explicit ,c0 falls back to ink so the text stays visible.
        color = self._resolve_stroke_color(mods)
        escaped = html.escape(text)
        # Rotate around the pen position. Because we're inside a y-flip <g>,
        # positive angle in language space (CCW) maps to negative angle in
        # SVG space (SVG rotates clockwise for positive). We compensate.
        rot = -angle
        # Text baseline: we want the pen at the baseline, first char to the right.
        self._body_parts.append(
            f'<g transform="translate({x} {y}) scale(1 -1) rotate({rot})">'
            f'<text x="0" y="0" font-family="{self.font_family}" '
            f'font-size="{size}" fill="{color}">{escaped}</text>'
            f'</g>'
        )

    def place_image(self, x, y, w, h, image_id):
        # For v0.1, emit a placeholder — the SVG references a data URI that
        # the caller can substitute later via string replacement or a proper
        # image-resolution callback. This keeps the interpreter/backend pure.
        placeholder_href = f"#image-{image_id}"
        self._body_parts.append(
            f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
            f'href="{placeholder_href}" preserveAspectRatio="none" '
            f'transform="scale(1 -1) translate(0 {-(2 * y + h)})" />'
        )
        self._track_bbox([(x, y), (x + w, y + h)])

    def finalize(self) -> str:
        # v0.6: viewBox is always auto-fit to the drawing's own bounding box
        # (unless the caller passed explicit width/height, e.g. PDF export).
        # This works uniformly for tiny symbols, A3 sheets, and oversized
        # pic_ex composites that legitimately span far more than A3.
        # Callers wanting an A3-locked view should pass explicit dimensions.
        A3_WIDTH = 1191
        A3_HEIGHT = 801
        if self.width is not None and self.height is not None:
            vb_x = self.origin_x
            vb_y = self.origin_y
            vb_w = self.width
            vb_h = self.height
        elif self._bbox is not None:
            xmin, ymin, xmax, ymax = self._bbox
            bbox_w = xmax - xmin
            bbox_h = ymax - ymin
            pad = max(4, min(bbox_w, bbox_h) * 0.05)
            vb_x = xmin - pad
            vb_y = ymin - pad
            vb_w = bbox_w + 2 * pad
            vb_h = bbox_h + 2 * pad
        else:
            # No geometry emitted at all: show blank A3.
            vb_x = 0
            vb_y = 0
            vb_w = A3_WIDTH
            vb_h = A3_HEIGHT

        # We render in language space (y-up). SVG is y-down. Apply a y-flip
        # transform on the root <g>. Then everything inside is in language
        # coordinates.
        body = "\n  ".join(self._body_parts)
        # Emit the SVG at its natural ES680 pixel size (1 language unit = 1
        # CSS pixel). This matches how ES680 itself rendered drawings on a
        # ~1024x900 workstation display: frames are exactly frame-sized, text
        # and line weights are legible, small detail templates fit normally.
        # Large templates (11000+ px picex sheets) will overflow the viewport;
        # the preview UI provides pan+zoom around them, again matching ES680.
        # data-content-width / data-content-height duplicate the size so a
        # zoom controller can read them without parsing the viewBox.
        # vector-effect="non-scaling-stroke" on the outer g forces every child
        # stroke to render at its authored pixel width regardless of any
        # CSS transform scale that the preview applies. This is what makes
        # a huge picex sheet (11000+ px) legible when zoomed out: 1-px lines
        # stay 1 CSS px, tick marks stay visible, text stays crisp. It has
        # no effect at 1:1 zoom, and it matches ES680's own cosmetic-line
        # behaviour on lower-resolution displays.
        # Embedded stylesheet forces every stroked primitive to use
        # vector-effect:non-scaling-stroke, so lines stay 1 CSS px wide at
        # every zoom level. non-scaling-stroke is not inherited via SVG
        # attributes, so an in-document <style> rule is the cleanest way
        # to apply it uniformly without touching per-primitive emitters.
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{vb_x} {-(vb_y + vb_h)} {vb_w} {vb_h}" '
            f'width="100%" height="100%" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'data-content-width="{vb_w}" data-content-height="{vb_h}">\n'
            f'  <style>line,rect,path,polyline,polygon,circle,ellipse'
            f'{{vector-effect:non-scaling-stroke}}</style>\n'
            f'  <g transform="scale(1 -1)">\n'
            f'    {body}\n'
            f'  </g>\n'
            f'</svg>'
        )

    # -- Internals -----------------------------------------------------------

    def _resolve_stroke_color(self, mods) -> str:
        """Stroke / text color.

        Spec v0.6: with no explicit `,c<n>`, stroke defaults to `ink`
        (palette index 1). An explicit `,c<n>` selects palette[n]; if that
        entry is `None` (paper), we fall back to ink so the stroke stays
        visible — an invisible stroke would erase the geometry entirely,
        which is what `,i` is for, not `,c0`.
        """
        idx = mods.get("color")
        if idx is None:
            idx = INK_INDEX
        color = self.palette.get(idx)
        if color is None:  # paper or missing entry — fall back to ink
            color = self.palette.get(INK_INDEX, "#000000")
        return color

    def _resolve_fill_color(self, mods) -> str:
        """Fill color (only meaningful when mods['fill'] is True).

        Spec v0.6: with no explicit `,c<n>`, fill defaults to `paper`
        (palette index 0), which renders as `fill="none"` — invisible.
        An explicit `,c<n>` selects palette[n] for the fill; palette[0]
        is paper (invisible); indices >=1 draw the actual color.
        """
        idx = mods.get("color")
        if idx is None:
            idx = PAPER_INDEX
        color = self.palette.get(idx)
        if color is None:  # paper — emit fill="none"
            return "none"
        return color

    def _stroke_attrs(self, mods) -> str:
        color = self._resolve_stroke_color(mods)
        parts = [
            f'stroke="{color}"',
            f'stroke-width="{self.stroke_width}"',
            'fill="none"',
        ]
        if mods["dashed"]:
            parts.append('stroke-dasharray="4 4"')
        return " ".join(parts)

    def _paint_attrs(self, mods) -> str:
        stroke_color = self._resolve_stroke_color(mods)
        parts = [
            f'stroke="{stroke_color}"',
            f'stroke-width="{self.stroke_width}"',
        ]
        if mods["fill"]:
            fill_color = self._resolve_fill_color(mods)
            parts.append(f'fill="{fill_color}"')
        else:
            parts.append('fill="none"')
        if mods["dashed"]:
            parts.append('stroke-dasharray="4 4"')
        return " ".join(parts)

    def _track_bbox(self, pts):
        for x, y in pts:
            if self._bbox is None:
                self._bbox = [float(x), float(y), float(x), float(y)]
            else:
                self._bbox[0] = min(self._bbox[0], x)
                self._bbox[1] = min(self._bbox[1], y)
                self._bbox[2] = max(self._bbox[2], x)
                self._bbox[3] = max(self._bbox[3], y)
