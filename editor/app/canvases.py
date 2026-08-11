"""
Drawing Language Editor — canvases storage.

A **canvas** is a named drawing. A **statement** is one row of drawlang code
belonging to a canvas, stored with its opcode, args, and 0-based sequence
position. Joining a canvas's statements in `seq` order reproduces the exact
drawlang program.

The database is the single source of truth. Rendering is a pure function of
the statements read from the database.

This module owns the schema + all read-only accessors. Step 4 will add the
statement-write API on top of these primitives.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from typing import Any

from . import storage as _storage


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS canvases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    frame_id     TEXT,
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_canvases_slug ON canvases(slug);
CREATE INDEX IF NOT EXISTS idx_canvases_updated_at ON canvases(updated_at DESC);

CREATE TABLE IF NOT EXISTS statements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    canvas_id    INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    opcode       TEXT    NOT NULL,
    args         TEXT    NOT NULL,
    group_id     TEXT,
    created_at   REAL    NOT NULL,
    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_statements_canvas
    ON statements(canvas_id, seq);
CREATE INDEX IF NOT EXISTS idx_statements_group
    ON statements(canvas_id, group_id);
"""


_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    """Reuse the drawings-module connection so both tables share one file."""
    return _storage._connect()


def init() -> None:
    """Apply canvas schema on top of the drawings schema. Idempotent."""
    with _lock:
        _conn().executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Program <-> statements round-trip helpers
# ---------------------------------------------------------------------------

# One drawlang statement: opcode + comma-separated args, terminated by `;`.
# Whitespace and blank lines outside statements are ignored.
# Comments (`# ...`) are stripped — they do not exist as rows.

_STMT_RE = re.compile(r"([a-z]{2})\s*((?:,[^;]*)?);", re.DOTALL)


def parse_program(source: str) -> list[tuple[str, str]]:
    """
    Split a drawlang program string into a list of (opcode, args) pairs
    in program order. Comments are dropped. Whitespace is preserved inside
    tx-style string arguments but leading/trailing whitespace on args
    is trimmed.
    """
    # Strip line comments (# ...) up to newline. We do not strip mid-line
    # because drawlang v0.6 doesn't allow mid-statement `#`.
    stripped = re.sub(r"#[^\n]*", "", source)
    out: list[tuple[str, str]] = []
    for m in _STMT_RE.finditer(stripped):
        opcode = m.group(1)
        raw_args = m.group(2)
        # `raw_args` starts with a leading `,` if any args present
        args = raw_args[1:].strip() if raw_args.startswith(",") else ""
        out.append((opcode, args))
    return out


def program_from_statements(rows: list[dict]) -> str:
    """Join statement rows into a drawlang program string in seq order."""
    parts = []
    for r in rows:
        if r["args"]:
            parts.append(f"{r['opcode']},{r['args']};")
        else:
            parts.append(f"{r['opcode']};")
    return "\n".join(parts) + ("\n" if parts else "")


# ---------------------------------------------------------------------------
# Canvas CRUD (create + read)
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Delegate to the shared slugifier."""
    return _storage.slugify(name)


def create_canvas(
    name: str,
    frame_id: str | None = None,
    program: str = "",
    slug: str | None = None,
) -> dict:
    """
    Create a new canvas. If `program` is given, parse it into statements
    and insert them in order. If `slug` collides, raise ValueError — the
    caller decides the resolution strategy.
    """
    canvas_slug = slug or _slug(name)
    now = time.time()
    with _lock:
        c = _conn()
        # Check for slug collision before opening a transaction so we don't
        # need to disentangle rollback state from the ValueError path.
        existing = c.execute(
            "SELECT id FROM canvases WHERE slug = ?", (canvas_slug,)
        ).fetchone()
        if existing:
            raise ValueError(f"canvas slug {canvas_slug!r} already exists")
        c.execute("BEGIN;")
        try:
            cur = c.execute(
                "INSERT INTO canvases (slug, name, frame_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (canvas_slug, name, frame_id, now, now),
            )
            canvas_id = cur.lastrowid
            if program:
                pairs = parse_program(program)
                c.executemany(
                    "INSERT INTO statements "
                    "(canvas_id, seq, opcode, args, group_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (canvas_id, seq, op, args, None, now)
                        for seq, (op, args) in enumerate(pairs)
                    ],
                )
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return get_canvas(canvas_slug) or {}  # type: ignore[return-value]


def list_canvases() -> list[dict]:
    """Return every canvas with its statement count."""
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT c.id, c.slug, c.name, c.frame_id, c.created_at, c.updated_at, "
            "  (SELECT COUNT(*) FROM statements s WHERE s.canvas_id = c.id) AS n "
            "FROM canvases c ORDER BY c.updated_at DESC"
        ).fetchall()
    return [
        {
            "id": row[0],
            "slug": row[1],
            "name": row[2],
            "frame_id": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "statement_count": row[6],
        }
        for row in rows
    ]


def _resolve_canvas_row(id_or_slug: str | int) -> tuple[int, str, str, str | None, float, float] | None:
    with _lock:
        c = _conn()
        if isinstance(id_or_slug, int) or (isinstance(id_or_slug, str) and id_or_slug.isdigit()):
            row = c.execute(
                "SELECT id, slug, name, frame_id, created_at, updated_at "
                "FROM canvases WHERE id = ?", (int(id_or_slug),)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT id, slug, name, frame_id, created_at, updated_at "
                "FROM canvases WHERE slug = ?", (id_or_slug,)
            ).fetchone()
    return row


def get_canvas(id_or_slug: str | int) -> dict | None:
    """Return canvas metadata + statements in seq order."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return None
    canvas_id = row[0]
    with _lock:
        c = _conn()
        stmt_rows = c.execute(
            "SELECT id, seq, opcode, args, group_id "
            "FROM statements WHERE canvas_id = ? ORDER BY seq ASC",
            (canvas_id,),
        ).fetchall()
    return {
        "canvas": {
            "id": row[0],
            "slug": row[1],
            "name": row[2],
            "frame_id": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        },
        "statements": [
            {
                "id": s[0],
                "seq": s[1],
                "opcode": s[2],
                "args": s[3],
                "group_id": s[4],
            }
            for s in stmt_rows
        ],
    }


def get_canvas_program(id_or_slug: str | int) -> str | None:
    """Reconstruct the drawlang program for a canvas."""
    data = get_canvas(id_or_slug)
    if data is None:
        return None
    return program_from_statements(data["statements"])


def delete_canvas(id_or_slug: str | int) -> bool:
    """Delete a canvas + all its statements (cascade)."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return False
    canvas_id = row[0]
    with _lock:
        c = _conn()
        c.execute("DELETE FROM canvases WHERE id = ?", (canvas_id,))
    return True


__all__ = [
    "init",
    "parse_program",
    "program_from_statements",
    "create_canvas",
    "list_canvases",
    "get_canvas",
    "get_canvas_program",
    "delete_canvas",
]
