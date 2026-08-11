"""
Editor-facing catalog of drawlang v0.6 opcodes.

Serves the Primitives tab. Each entry is one opcode from the language:
7 core (spec §6) + 4 extension (spec §7). No composition, no invented
shapes. The editor renders one editable row per opcode; args are the
opcode's spec-declared arguments.

Kept in-repo so the language and the editor stay in lockstep: when the
spec adds an opcode, this list gains one row and the Primitives tab
automatically exposes it.
"""

from __future__ import annotations

from typing import Any


# Argument type notes:
#   int_signed  - signed 16-bit integer (v0.3 unified numeric type)
#   text        - free ASCII, no commas or semicolons unless quoted per grammar
#   modifier    - optional string flag like 'i', 't', 'f', 'c0'..'cN'
#
# `default` is used as the pre-fill value in the Edit Selected form. Sensible
# small values that produce something visible when placed on canvas.

CORE_OPCODES: list[dict[str, Any]] = [
    {
        "opcode": "mr",
        "name": "Move relative",
        "group": "core",
        "description": "Move the pen by (dx, dy). No mark is drawn.",
        "spec_section": "§6.1",
        "args": [
            {"name": "dx", "type": "int", "default": 10},
            {"name": "dy", "type": "int", "default": 0},
        ],
    },
    {
        "opcode": "ma",
        "name": "Move absolute",
        "group": "core",
        "description": "Move the pen to absolute point (x, y). No mark drawn.",
        "spec_section": "§6.2",
        "args": [
            {"name": "x", "type": "int", "default": 0},
            {"name": "y", "type": "int", "default": 0},
        ],
    },
    {
        "opcode": "dl",
        "name": "Draw line (relative)",
        "group": "core",
        "description": "Draw a line from the current pen position by (dx, dy). "
                       "Modifier 'i' makes the line invisible (advances only).",
        "spec_section": "§6.3",
        "args": [
            {"name": "dx", "type": "int", "default": 40},
            {"name": "dy", "type": "int", "default": 0},
        ],
    },
    {
        "opcode": "da",
        "name": "Draw line (absolute)",
        "group": "core",
        "description": "Draw a line from the current pen position to absolute (x, y).",
        "spec_section": "§6.3",
        "args": [
            {"name": "x", "type": "int", "default": 100},
            {"name": "y", "type": "int", "default": 100},
        ],
    },
    {
        "opcode": "rt",
        "name": "Rectangle",
        "group": "core",
        "description": "Draw a rectangle with width W and height H, anchored at "
                       "the current pen position. Modifiers: 'i' (invisible), "
                       "'t' (reserved), 'f' (filled with paper by default).",
        "spec_section": "§6.4",
        "args": [
            {"name": "w", "type": "int", "default": 60},
            {"name": "h", "type": "int", "default": 40},
        ],
    },
    {
        "opcode": "ci",
        "name": "Circle",
        "group": "core",
        "description": "Draw a circle of radius r centered at the current pen "
                       "position. Modifiers: 't' (reserved), 'f' (filled).",
        "spec_section": "§6.5",
        "args": [
            {"name": "r", "type": "int", "default": 20},
        ],
    },
    {
        "opcode": "tx",
        "name": "Text",
        "group": "core",
        "description": "Draw text at the current pen position at the given size.",
        "spec_section": "§6.6",
        "args": [
            {"name": "size", "type": "int", "default": 12},
            {"name": "text", "type": "text", "default": "Text"},
        ],
    },
]


EXTENSION_OPCODES: list[dict[str, Any]] = [
    {
        "opcode": "ar",
        "name": "Arc",
        "group": "extension",
        "description": "Draw an arc segment of radius r from start angle to end "
                       "angle (integer degrees). See spec §7.",
        "spec_section": "§7.1",
        "args": [
            {"name": "r", "type": "int", "default": 25},
            {"name": "start", "type": "int", "default": 0},
            {"name": "sweep", "type": "int", "default": 90},
        ],
    },
    {
        "opcode": "bz",
        "name": "Bezier",
        "group": "extension",
        "description": "Draw a cubic Bezier curve using two control points and "
                       "an end point, all relative to the current pen position.",
        "spec_section": "§7.2",
        "args": [
            {"name": "cx1", "type": "int", "default": 20},
            {"name": "cy1", "type": "int", "default": -20},
            {"name": "cx2", "type": "int", "default": 60},
            {"name": "cy2", "type": "int", "default": -20},
            {"name": "ex", "type": "int", "default": 80},
            {"name": "ey", "type": "int", "default": 0},
        ],
    },
    {
        "opcode": "po",
        "name": "Polyline",
        "group": "extension",
        "description": "Draw a polyline through N points, given as a "
                       "comma-separated list of dx,dy pairs relative to the "
                       "current pen position.",
        "spec_section": "§7.3",
        "args": [
            {"name": "points", "type": "text", "default": "0,0,40,0,40,40,0,40"},
        ],
    },
    {
        "opcode": "ra",
        "name": "Raster",
        "group": "extension",
        "description": "Reference a raster image asset by id, placed at the "
                       "current pen position with given width and height.",
        "spec_section": "§7.4",
        "args": [
            {"name": "id", "type": "int", "default": 1},
            {"name": "w", "type": "int", "default": 100},
            {"name": "h", "type": "int", "default": 60},
        ],
    },
]


ALL_OPCODES: list[dict[str, Any]] = CORE_OPCODES + EXTENSION_OPCODES


def list_opcodes() -> list[dict[str, Any]]:
    """Return the full opcode catalog for the editor Primitives tab."""
    return ALL_OPCODES


def get_opcode(opcode: str) -> dict[str, Any] | None:
    """Look up a single opcode by its two-letter mnemonic."""
    for op in ALL_OPCODES:
        if op["opcode"] == opcode:
            return op
    return None
