"""
Reference interpreter — spec §9.

Reads parsed statements and drives a backend. The backend is any object
that implements the abstract interface in backend.py. The interpreter itself
knows nothing about SVG, PostScript, or any output format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .errors import SemanticError
from .parser import Modifier, Statement, parse
from .backend import Backend


@dataclass
class PenState:
    """Pen state per spec §5.1."""

    x: int = 0
    y: int = 0
    text_size: int = 10


def interpret(program: str | Iterable[Statement], backend: Backend) -> PenState:
    """
    Execute a program against a backend.

    `program` is either a raw cmd string (which will be parsed) or an already-
    parsed list of Statement objects (useful for concatenating multiple `lau`
    rows before executing — spec §11.2).

    Returns the final PenState (useful for tests and debugging).
    """
    if isinstance(program, str):
        statements = parse(program)
    else:
        statements = list(program)

    pen = PenState()
    for stmt in statements:
        _execute(stmt, pen, backend)
    return pen


# ---------------------------------------------------------------------------
# Per-opcode execution — one function per opcode, mirrors spec §6-§7 exactly.
# ---------------------------------------------------------------------------


def _execute(stmt: Statement, pen: PenState, backend: Backend) -> None:
    op = stmt.opcode
    fn = _DISPATCH[op]
    fn(stmt, pen, backend)


# ---- Core opcodes (spec §6) ------------------------------------------------


def _op_mr(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """mr,dx,dy — move relative (spec §6.1)."""
    dx, dy = stmt.args
    pen.x += dx
    pen.y += dy


def _op_ma(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """ma,x,y — move absolute (spec §6.2)."""
    x, y = stmt.args
    pen.x = x
    pen.y = y


def _op_dl(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """dl,dx,dy — draw line relative (spec §6.3). Pen advances to endpoint."""
    dx, dy = stmt.args
    x1, y1 = pen.x, pen.y
    x2, y2 = pen.x + dx, pen.y + dy
    backend.draw_line(x1, y1, x2, y2, _mods_dict(stmt))
    pen.x, pen.y = x2, y2


def _op_rt(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """rt,w,h[,f][,i] — rectangle (spec §6.4). Pen unchanged."""
    w, h = stmt.args
    backend.draw_rectangle(pen.x, pen.y, w, h, _mods_dict(stmt))


def _op_ci(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """ci,r[,f] — circle (spec §6.5). Pen unchanged."""
    (r,) = stmt.args
    if r <= 0:
        raise SemanticError(
            f"'ci': radius must be positive, got {r} (spec §6.5)",
            statement_index=stmt.source_index,
        )
    backend.draw_circle(pen.x, pen.y, r, _mods_dict(stmt))


def _op_tz(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """tz,size — set text size (spec §6.6). Pen position unchanged."""
    (size,) = stmt.args
    if size <= 0:
        raise SemanticError(
            f"'tz': size must be positive, got {size} (spec §6.6)",
            statement_index=stmt.source_index,
        )
    pen.text_size = size


def _op_tx(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """tx,angle,string — draw text (spec §6.7). Pen unchanged."""
    angle, text = stmt.args
    backend.draw_text(pen.x, pen.y, pen.text_size, angle, text, _mods_dict(stmt))


# ---- Extension opcodes (spec §7) ------------------------------------------


def _op_ar(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """ar,r,start,sweep[,f] — arc (spec §7.1). Pen unchanged (center stays)."""
    r, start_angle, sweep_angle = stmt.args
    if r <= 0:
        raise SemanticError(
            f"'ar': radius must be positive, got {r} (spec §7.1)",
            statement_index=stmt.source_index,
        )
    backend.draw_arc(pen.x, pen.y, r, start_angle, sweep_angle, _mods_dict(stmt))


def _op_bz(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """bz,dx1,dy1,dx2,dy2,dx3,dy3 — cubic Bézier (spec §7.2). Pen advances to P3."""
    dx1, dy1, dx2, dy2, dx3, dy3 = stmt.args
    p0 = (pen.x, pen.y)
    p1 = (pen.x + dx1, pen.y + dy1)
    p2 = (pen.x + dx2, pen.y + dy2)
    p3 = (pen.x + dx3, pen.y + dy3)
    backend.draw_bezier(p0, p1, p2, p3, _mods_dict(stmt))
    pen.x, pen.y = p3


def _op_sp(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """
    sp,x1,y1,...,xN,yN — spline through anchor points (spec §7.3).

    Catmull-Rom (tension 0.5) → cubic Bézier conversion. Compliance with
    spec §7.3 requires that ALL interpreters use this exact conversion so
    that all backends produce identical output.

    Pen advances to the last anchor.
    """
    args = stmt.args
    anchors = list(zip(args[0::2], args[1::2]))
    # Convert to Béziers and emit them one at a time
    for (p0, p1, p2, p3) in _catmull_rom_to_beziers(anchors, tension=0.5):
        backend.draw_bezier(p0, p1, p2, p3, _mods_dict(stmt))
    pen.x, pen.y = anchors[-1]


def _op_im(stmt: Statement, pen: PenState, backend: Backend) -> None:
    """im,w,h,image_id — raster image placement (spec §7.4). Pen unchanged."""
    w, h, image_id = stmt.args
    backend.place_image(pen.x, pen.y, w, h, image_id)


# ---- Dispatch table -------------------------------------------------------

_DISPATCH = {
    # Core
    "mr": _op_mr,
    "ma": _op_ma,
    "dl": _op_dl,
    "rt": _op_rt,
    "ci": _op_ci,
    "tz": _op_tz,
    "tx": _op_tx,
    # Extensions
    "ar": _op_ar,
    "bz": _op_bz,
    "sp": _op_sp,
    "im": _op_im,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mods_dict(stmt: Statement) -> dict:
    """
    Package the statement's modifiers into a dict for the backend.

    Keys: 'fill' (bool), 'invisible' (bool), 'dashed' (bool), 'color' (int|None).
    Backends only need to look up what they support.
    """
    d = {"fill": False, "invisible": False, "dashed": False, "color": None}
    for m in stmt.modifiers:
        if m.name == "f":
            d["fill"] = True
        elif m.name == "i":
            d["invisible"] = True
        elif m.name == "d":
            d["dashed"] = True
        elif m.name == "c":
            d["color"] = m.color_index
    return d


def _catmull_rom_to_beziers(
    anchors: list[tuple[int, int]], tension: float = 0.5
) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """
    Convert a list of Catmull-Rom anchors to a list of cubic Bézier segments.

    Exact algorithm per spec §7.3:
        cp1 = Pi + (Pi+1 − Pi-1) / 6
        cp2 = Pi+1 − (Pi+2 − Pi) / 6
    with endpoint clamping: P-1 = P0, PN+1 = PN.

    Returns a list of (P0, P1, P2, P3) tuples.
    """
    if len(anchors) < 2:
        return []

    # Extend with clamped endpoints
    ext = [anchors[0]] + list(anchors) + [anchors[-1]]

    segments = []
    for i in range(1, len(ext) - 2):
        p_prev = ext[i - 1]
        p0 = ext[i]
        p1 = ext[i + 1]
        p_next = ext[i + 2]

        # Bezier control points from Catmull-Rom (tension = 0.5 → factor 1/6)
        # Higher tension = smaller factor. tension=0.5 is the canonical value.
        factor = (1.0 - tension) / 3.0  # = 1/6 when tension=0.5
        cp1 = (p0[0] + (p1[0] - p_prev[0]) * factor,
               p0[1] + (p1[1] - p_prev[1]) * factor)
        cp2 = (p1[0] - (p_next[0] - p0[0]) * factor,
               p1[1] - (p_next[1] - p0[1]) * factor)
        segments.append((p0, cp1, cp2, p1))

    return segments
