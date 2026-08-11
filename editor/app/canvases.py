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

# Additive migrations. Each entry is (column_name, DDL fragment). Runs after
# SCHEMA and swallows the "duplicate column" error so init() stays idempotent.
_MIGRATIONS = [
    ("meaning_tag", "ALTER TABLE statements ADD COLUMN meaning_tag TEXT"),
]


_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    """Reuse the drawings-module connection so both tables share one file."""
    return _storage._connect()


def init() -> None:
    """Apply canvas schema on top of the drawings schema. Idempotent.

    Also applies any additive migrations (see `_MIGRATIONS`). We check for
    the column first rather than catching the ALTER error so that a bad
    migration doesn't get silently swallowed.
    """
    with _lock:
        c = _conn()
        c.executescript(SCHEMA)
        existing_cols = {
            row[1] for row in c.execute("PRAGMA table_info(statements)").fetchall()
        }
        for col_name, ddl in _MIGRATIONS:
            if col_name not in existing_cols:
                c.execute(ddl)


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
            "SELECT id, seq, opcode, args, group_id, meaning_tag "
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
                "meaning_tag": s[5],
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


def update_canvas(
    id_or_slug: str | int,
    *,
    name: str | None = None,
    slug: str | None = None,
    frame_id: str | None = None,
) -> dict | None:
    """Patch a canvas's name / slug / frame_id.

    Any argument left as None is preserved. To *clear* frame_id (turn a
    framed canvas into a blank one) pass the sentinel string ``""`` — it
    is stored as SQL NULL.

    Returns the updated canvas dict, or None if the target does not exist.
    Raises ValueError on slug collision with a different canvas.
    """
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return None
    canvas_id = row[0]

    fields: list[str] = []
    values: list[object] = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)

    if slug is not None:
        # Check for collision against a DIFFERENT canvas.
        with _lock:
            existing = _conn().execute(
                "SELECT id FROM canvases WHERE slug = ? AND id != ?",
                (slug, canvas_id),
            ).fetchone()
        if existing:
            raise ValueError(f"canvas slug {slug!r} already exists")
        fields.append("slug = ?")
        values.append(slug)

    if frame_id is not None:
        fields.append("frame_id = ?")
        # Empty string means "clear".
        values.append(frame_id if frame_id != "" else None)

    if not fields:
        # No-op patch — still return the current row's metadata.
        data = get_canvas(canvas_id)
        return data["canvas"] if data else None

    now = time.time()
    fields.append("updated_at = ?")
    values.append(now)
    values.append(canvas_id)

    with _lock:
        c = _conn()
        c.execute(
            f"UPDATE canvases SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    data = get_canvas(canvas_id)
    return data["canvas"] if data else None


__all__ = [
    "init",
    "parse_program",
    "program_from_statements",
    "create_canvas",
    "list_canvases",
    "get_canvas",
    "get_canvas_program",
    "delete_canvas",
    "update_canvas",
]


# ---------------------------------------------------------------------------
# Step 4: statement write API
# ---------------------------------------------------------------------------

def _touch_canvas(c: sqlite3.Connection, canvas_id: int, now: float) -> None:
    c.execute("UPDATE canvases SET updated_at = ? WHERE id = ?", (now, canvas_id))


def append_statements(
    id_or_slug: str | int,
    statements: list[dict],
) -> list[dict]:
    """
    Append one or more statements to a canvas. Each item is {opcode, args, group_id?}.
    Assigns seq = current max + 1, +2, ...
    """
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        raise KeyError("canvas not found")
    canvas_id = row[0]
    now = time.time()
    inserted_ids: list[int] = []
    with _lock:
        c = _conn()
        c.execute("BEGIN;")
        try:
            max_seq_row = c.execute(
                "SELECT COALESCE(MAX(seq), -1) FROM statements WHERE canvas_id = ?",
                (canvas_id,),
            ).fetchone()
            next_seq = (max_seq_row[0] if max_seq_row else -1) + 1
            for s in statements:
                op = s["opcode"]
                args = s.get("args", "")
                group_id = s.get("group_id")
                meaning_tag = s.get("meaning_tag")
                cur = c.execute(
                    "INSERT INTO statements (canvas_id, seq, opcode, args, "
                    "group_id, meaning_tag, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (canvas_id, next_seq, op, args, group_id, meaning_tag, now),
                )
                inserted_ids.append(cur.lastrowid)
                next_seq += 1
            _touch_canvas(c, canvas_id, now)
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return _fetch_statements_by_ids(inserted_ids)


def append_program(id_or_slug: str | int, program: str) -> list[dict]:
    """Append a raw drawlang program to a canvas, one row per statement."""
    pairs = parse_program(program)
    return append_statements(
        id_or_slug,
        [{"opcode": op, "args": args} for op, args in pairs],
    )


def update_statement(
    id_or_slug: str | int, statement_id: int, patch: dict
) -> dict | None:
    """Update opcode / args / group_id on a single statement."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return None
    canvas_id = row[0]
    now = time.time()
    with _lock:
        c = _conn()
        existing = c.execute(
            "SELECT id, seq, opcode, args, group_id, meaning_tag FROM statements "
            "WHERE id = ? AND canvas_id = ?",
            (statement_id, canvas_id),
        ).fetchone()
        if existing is None:
            return None
        new_opcode = patch.get("opcode", existing[2])
        new_args = patch.get("args", existing[3])
        new_group = patch.get("group_id", existing[4])
        # meaning_tag is treated distinctly: an explicit None in the patch
        # clears the tag; a missing key preserves the current value.
        if "meaning_tag" in patch:
            new_meaning = patch["meaning_tag"]
        else:
            new_meaning = existing[5]
        c.execute("BEGIN;")
        try:
            c.execute(
                "UPDATE statements SET opcode = ?, args = ?, group_id = ?, "
                "meaning_tag = ? WHERE id = ?",
                (new_opcode, new_args, new_group, new_meaning, statement_id),
            )
            _touch_canvas(c, canvas_id, now)
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return _fetch_statements_by_ids([statement_id])[0]


def delete_statement(id_or_slug: str | int, statement_id: int) -> bool:
    """Delete one statement. Does NOT compact the seq numbers of the rest."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return False
    canvas_id = row[0]
    now = time.time()
    with _lock:
        c = _conn()
        c.execute("BEGIN;")
        try:
            cur = c.execute(
                "DELETE FROM statements WHERE id = ? AND canvas_id = ?",
                (statement_id, canvas_id),
            )
            if cur.rowcount == 0:
                c.execute("ROLLBACK;")
                return False
            _touch_canvas(c, canvas_id, now)
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return True


def reorder_statements(
    id_or_slug: str | int, order: list[int]
) -> bool:
    """
    Reassign seq numbers based on the given ordered list of statement ids.
    Any statement id not in `order` gets moved to the end in its current
    relative order. Ids that don't belong to this canvas are ignored.
    """
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return False
    canvas_id = row[0]
    now = time.time()
    with _lock:
        c = _conn()
        c.execute("BEGIN;")
        try:
            all_ids = [
                r[0] for r in c.execute(
                    "SELECT id FROM statements WHERE canvas_id = ? ORDER BY seq ASC",
                    (canvas_id,),
                ).fetchall()
            ]
            id_set = set(all_ids)
            new_order = [i for i in order if i in id_set]
            leftovers = [i for i in all_ids if i not in set(new_order)]
            final = new_order + leftovers
            for seq, sid in enumerate(final):
                c.execute(
                    "UPDATE statements SET seq = ? WHERE id = ?",
                    (seq, sid),
                )
            _touch_canvas(c, canvas_id, now)
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return True


def replace_program(id_or_slug: str | int, program: str) -> dict | None:
    """Delete all statements on a canvas and repopulate from a raw program."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return None
    canvas_id = row[0]
    now = time.time()
    pairs = parse_program(program)
    with _lock:
        c = _conn()
        c.execute("BEGIN;")
        try:
            c.execute("DELETE FROM statements WHERE canvas_id = ?", (canvas_id,))
            for seq, (op, args) in enumerate(pairs):
                c.execute(
                    "INSERT INTO statements (canvas_id, seq, opcode, args, "
                    "group_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (canvas_id, seq, op, args, None, now),
                )
            _touch_canvas(c, canvas_id, now)
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return get_canvas(id_or_slug)


def _fetch_statements_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _lock:
        c = _conn()
        rows = c.execute(
            f"SELECT id, seq, opcode, args, group_id, meaning_tag FROM statements "
            f"WHERE id IN ({placeholders}) ORDER BY seq ASC",
            ids,
        ).fetchall()
    return [
        {
            "id": r[0],
            "seq": r[1],
            "opcode": r[2],
            "args": r[3],
            "group_id": r[4],
            "meaning_tag": r[5],
        }
        for r in rows
    ]


def list_statements_by_meaning(
    id_or_slug: str | int, meaning_tag: str
) -> list[dict]:
    """Return all statements on a canvas that carry a given meaning_tag."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return []
    canvas_id = row[0]
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT id, seq, opcode, args, group_id, meaning_tag "
            "FROM statements WHERE canvas_id = ? AND meaning_tag = ? "
            "ORDER BY seq ASC",
            (canvas_id, meaning_tag),
        ).fetchall()
    return [
        {
            "id": r[0],
            "seq": r[1],
            "opcode": r[2],
            "args": r[3],
            "group_id": r[4],
            "meaning_tag": r[5],
        }
        for r in rows
    ]


def list_meaning_index(id_or_slug: str | int) -> list[dict]:
    """Return the distinct meaning_tag values on a canvas + statement counts."""
    row = _resolve_canvas_row(id_or_slug)
    if row is None:
        return []
    canvas_id = row[0]
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT meaning_tag, COUNT(*) FROM statements "
            "WHERE canvas_id = ? AND meaning_tag IS NOT NULL "
            "GROUP BY meaning_tag ORDER BY meaning_tag ASC",
            (canvas_id,),
        ).fetchall()
    return [{"meaning_tag": r[0], "count": r[1]} for r in rows]


__all__ += [
    "append_statements",
    "append_program",
    "update_statement",
    "delete_statement",
    "reorder_statements",
    "replace_program",
    "list_statements_by_meaning",
    "list_meaning_index",
]
