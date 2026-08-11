"""
Drawing Language Editor — user library storage.

A **library item** is a reusable named block of drawlang statements
(a symbol, sub-circuit, or template). Items belong to categories and can
be dropped into any canvas by generating a translated copy of their
statements at a target coordinate.
"""

from __future__ import annotations

import sqlite3
import threading
import time

from . import storage as _storage
from . import canvases as _canvases


SCHEMA = """
CREATE TABLE IF NOT EXISTS library_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    category     TEXT    NOT NULL DEFAULT 'symbol',
    description  TEXT,
    program      TEXT    NOT NULL,
    anchor_x     REAL    NOT NULL DEFAULT 0,
    anchor_y     REAL    NOT NULL DEFAULT 0,
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_slug ON library_items(slug);
CREATE INDEX IF NOT EXISTS idx_library_category ON library_items(category);
"""

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return _storage._connect()


def _fmt(n: float) -> str:
    """Format a number the way drawlang expects: int if whole, else float."""
    if float(n).is_integer():
        return str(int(n))
    return str(n)


def init() -> None:
    with _lock:
        _conn().executescript(SCHEMA)


def create_item(
    name: str,
    program: str,
    category: str = "symbol",
    description: str = "",
    anchor_x: float = 0.0,
    anchor_y: float = 0.0,
    slug: str | None = None,
) -> dict:
    item_slug = slug or _storage.slugify(name)
    now = time.time()
    with _lock:
        c = _conn()
        exists = c.execute(
            "SELECT id FROM library_items WHERE slug = ?", (item_slug,)
        ).fetchone()
        if exists:
            raise ValueError(f"library slug {item_slug!r} already exists")
        c.execute(
            "INSERT INTO library_items "
            "(slug, name, category, description, program, anchor_x, anchor_y, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_slug, name, category, description, program,
             anchor_x, anchor_y, now, now),
        )
    return get_item(item_slug)  # type: ignore[return-value]


def get_item(id_or_slug: str | int) -> dict | None:
    with _lock:
        c = _conn()
        if isinstance(id_or_slug, int) or (isinstance(id_or_slug, str) and id_or_slug.isdigit()):
            row = c.execute(
                "SELECT id, slug, name, category, description, program, "
                "anchor_x, anchor_y, created_at, updated_at "
                "FROM library_items WHERE id = ?", (int(id_or_slug),)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT id, slug, name, category, description, program, "
                "anchor_x, anchor_y, created_at, updated_at "
                "FROM library_items WHERE slug = ?", (id_or_slug,)
            ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0], "slug": row[1], "name": row[2], "category": row[3],
        "description": row[4] or "", "program": row[5],
        "anchor_x": row[6], "anchor_y": row[7],
        "created_at": row[8], "updated_at": row[9],
    }


def list_items(category: str | None = None) -> list[dict]:
    with _lock:
        c = _conn()
        if category:
            rows = c.execute(
                "SELECT slug FROM library_items WHERE category = ? "
                "ORDER BY name ASC", (category,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT slug FROM library_items ORDER BY category, name ASC"
            ).fetchall()
    return [get_item(r[0]) for r in rows if get_item(r[0]) is not None]  # type: ignore[misc]


def update_item(id_or_slug: str | int, patch: dict) -> dict | None:
    item = get_item(id_or_slug)
    if item is None:
        return None
    fields = {}
    for k in ("name", "category", "description", "program",
              "anchor_x", "anchor_y"):
        if k in patch and patch[k] is not None:
            fields[k] = patch[k]
    if not fields:
        return item
    now = time.time()
    with _lock:
        c = _conn()
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys()) + ", updated_at = ?"
        c.execute(
            f"UPDATE library_items SET {set_clause} WHERE id = ?",
            list(fields.values()) + [now, item["id"]],
        )
    return get_item(item["id"])


def delete_item(id_or_slug: str | int) -> bool:
    item = get_item(id_or_slug)
    if item is None:
        return False
    with _lock:
        c = _conn()
        c.execute("DELETE FROM library_items WHERE id = ?", (item["id"],))
    return True


# ---------------------------------------------------------------------------
# Drop a library item onto a canvas (Step 8 uses this)
# ---------------------------------------------------------------------------

def drop_on_canvas(
    library_id_or_slug: str | int,
    canvas_id_or_slug: str | int,
    x: float,
    y: float,
    group_id: str | None = None,
) -> list[dict]:
    """
    Insert a library item's statements onto a canvas, positioned at (x, y).

    Strategy: prepend `ma,x,y;` to move the absolute pen to the drop point,
    then append the library program's statements verbatim as a group.
    Coordinates inside the library program are assumed to be relative to
    the item's own anchor (usually 0,0).
    """
    item = get_item(library_id_or_slug)
    if item is None:
        raise KeyError("library item not found")

    canvas_row = _canvases._resolve_canvas_row(canvas_id_or_slug)
    if canvas_row is None:
        raise KeyError("canvas not found")

    dx = x - item["anchor_x"]
    dy = y - item["anchor_y"]
    prelude = [{"opcode": "ma", "args": f"{_fmt(dx)},{_fmt(dy)}", "group_id": group_id}]
    pairs = _canvases.parse_program(item["program"])
    body = [
        {"opcode": op, "args": args, "group_id": group_id}
        for op, args in pairs
    ]
    return _canvases.append_statements(canvas_id_or_slug, prelude + body)


__all__ = [
    "init", "create_item", "get_item", "list_items",
    "update_item", "delete_item", "drop_on_canvas",
]
