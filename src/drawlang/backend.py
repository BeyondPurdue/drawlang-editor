"""
Abstract backend interface — spec §9 "the backend object".

Every concrete backend (SVG, PostScript, and any future addition like PDF,
Canvas 2D for the editor, etc.) implements this interface. The interpreter
calls these methods; the backend translates them into output-format-specific
syntax.

Method conventions:

- All coordinates and lengths are integers in the drawing's abstract units.
  The backend is responsible for any final coordinate transformation (e.g.
  y-flip for SVG's y-down coordinate system).
- All angles are in degrees, counterclockwise positive, with 0° pointing
  along +X (spec §4.1, §4.2).
- The `mods` argument is a dict with keys 'fill', 'invisible', 'dashed',
  'color' (see interpreter.py::_mods_dict). Backends look up only what they
  care about.
- `finalize()` returns the complete output as a string (or bytes for binary
  formats — but neither SVG nor PostScript are binary).
"""

from __future__ import annotations

from typing import Protocol


class Backend(Protocol):
    """Structural interface — any object with these methods is a valid backend."""

    def draw_line(
        self, x1: int, y1: int, x2: int, y2: int, mods: dict
    ) -> None: ...
    def draw_rectangle(
        self, x: int, y: int, w: int, h: int, mods: dict
    ) -> None: ...
    def draw_circle(
        self, cx: int, cy: int, r: int, mods: dict
    ) -> None: ...
    def draw_arc(
        self, cx: int, cy: int, r: int, start_angle: float, sweep_angle: float,
        mods: dict,
    ) -> None: ...
    def draw_bezier(
        self, p0: tuple, p1: tuple, p2: tuple, p3: tuple, mods: dict
    ) -> None: ...
    def draw_text(
        self, x: int, y: int, size: int, angle: float, text: str, mods: dict
    ) -> None: ...
    def place_image(
        self, x: int, y: int, w: int, h: int, image_id: int
    ) -> None: ...
    def finalize(self) -> str: ...
