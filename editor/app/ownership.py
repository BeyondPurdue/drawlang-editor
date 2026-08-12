"""
v0.8 — add owner_id columns to existing tables.

Idempotent. Runs on startup, after auth.init() has created the users
table + seeded demo/admin, and after each of the domain modules has
created its own tables. Existing rows (from pre-v0.8 databases) are
backfilled to the admin user's id.
"""

from __future__ import annotations

import sqlite3
import threading

from . import storage as _storage
from . import auth as _auth


_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return _storage._connect()


def _has_column(table: str, column: str) -> bool:
    rows = _conn().execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        # sqlite3.Row or tuple: column name is index 1
        name = r[1] if not isinstance(r, sqlite3.Row) else r["name"]
        if name == column:
            return True
    return False


def _admin_id() -> int | None:
    """Return the seeded admin's id, or None if auth.init() hasn't run yet.

    Tests use temp DBs and only call the domain-module ``init()`` fns, so
    the users table may not exist. In that case we still create the
    owner_id column, but leave existing rows unowned (backfill happens
    later when the app runs ``auth.init()`` + ``ownership.apply()``).
    """
    try:
        row = _conn().execute(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        try:
            row = _conn().execute(
                "SELECT id FROM users ORDER BY id ASC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    return int(row[0]) if row is not None else None


def _add_owner_column(table: str) -> None:
    if _has_column(table, "owner_id"):
        return
    admin = _admin_id()
    with _lock:
        c = _conn()
        # SQLite ALTER TABLE cannot add a FOREIGN KEY column with a NOT NULL
        # constraint on a table that already has rows without a default.
        # So: nullable + backfill + create an index. That's enough for our
        # per-user filtering; app-level checks enforce ownership.
        c.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER")
        if admin is not None:
            c.execute(f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL", (admin,))
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_owner ON {table}(owner_id)")
        c.commit()


def _apply_one(table: str) -> None:
    """Add owner_id to one table. Safe to call from domain-module init().

    Silently no-ops when the target table doesn't yet exist (the caller
    invokes this right before/after CREATE TABLE, order not guaranteed).
    """
    try:
        _conn().execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return
    _add_owner_column(table)


def apply() -> None:
    """Add owner_id column to every owned table. Idempotent."""
    for table in ("canvases", "frames", "library_items"):
        _apply_one(table)


__all__ = ["apply", "_apply_one"]
