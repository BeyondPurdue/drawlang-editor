"""
Drawing Language Editor — SQLite storage for user drawings.

Every user-saved drawing is a database record, as the spec requires:
"Programs are stored as rows in a database. The interpreter reads programs
from the database and produces output. The database is authoritative;
the rendered output is derived, disposable, and reproducible."

This module intentionally uses only the Python stdlib (sqlite3) — no
SQLAlchemy — so deployments have zero extra dependencies. Migrating to
PostgreSQL later is a matter of swapping this file for a psycopg-based
equivalent that implements the same ~30-line contract.

Schema is defined once, in Python, and applied idempotently on startup.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

def _resolve_db_path() -> Path:
    """
    Location precedence:
      1. $DRAWLANG_DB_PATH (absolute) — production override
      2. <repo-root>/data/drawings.db — default, on the deploy host
    """
    override = os.environ.get("DRAWLANG_DB_PATH")
    if override:
        return Path(override)
    # editor/app/storage.py → editor/app → editor → <repo-root>
    repo_root = Path(__file__).resolve().parent.parent.parent
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "drawings.db"


DB_PATH = _resolve_db_path()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS drawings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    program      TEXT    NOT NULL,
    source_id    TEXT,
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drawings_slug ON drawings(slug);
CREATE INDEX IF NOT EXISTS idx_drawings_updated_at ON drawings(updated_at DESC);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

# One connection per process, guarded by a lock for the small number of
# writes we expect. SQLite in WAL mode handles concurrent readers natively.

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(
            DB_PATH,
            check_same_thread=False,
            isolation_level=None,   # autocommit; we use explicit transactions
            timeout=5.0,
        )
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA foreign_keys=ON;")
        _conn.executescript(SCHEMA)
    return _conn


def init() -> None:
    """Force-open the connection and apply schema. Called from app startup."""
    _connect()


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip()) or "drawing"
    return slug.rstrip(".").rstrip("-") or "drawing"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def save_drawing(name: str, program: str, source_id: str | None = None) -> dict:
    """
    Insert or replace a drawing by slug (derived from name). Returns the
    row shape the /save endpoint promised: {"ok": True, "slug": ..., "path": ...}
    ("path" preserved for wire compatibility with the pre-DB API.)
    """
    slug = slugify(name)
    now = time.time()
    with _lock:
        c = _connect()
        c.execute("BEGIN;")
        try:
            existing = c.execute(
                "SELECT id FROM drawings WHERE slug = ?", (slug,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE drawings SET name = ?, program = ?, source_id = ?, "
                    "updated_at = ? WHERE slug = ?",
                    (name, program, source_id, now, slug),
                )
            else:
                c.execute(
                    "INSERT INTO drawings (slug, name, program, source_id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (slug, name, program, source_id, now, now),
                )
            c.execute("COMMIT;")
        except Exception:
            c.execute("ROLLBACK;")
            raise
    return {"ok": True, "slug": slug, "path": f"{slug}.cmd"}


def list_drawings() -> list[dict]:
    """
    Return every saved drawing in the shape the /drawings endpoint promised
    (list of {id, title, category, program, description}).
    """
    with _lock:
        c = _connect()
        rows = c.execute(
            "SELECT slug, name, program, source_id, updated_at "
            "FROM drawings ORDER BY updated_at DESC"
        ).fetchall()
    items = []
    for slug, name, program, source_id, updated_at in rows:
        desc = f"User drawing saved as {slug}.cmd."
        if source_id:
            desc = f"Forked from {source_id}. " + desc
        items.append({
            "id": f"user-{slug}",
            "title": name,
            "category": "My drawings",
            "program": program,
            "description": desc,
        })
    return items


def get_drawing(slug: str) -> dict | None:
    with _lock:
        c = _connect()
        row = c.execute(
            "SELECT slug, name, program, source_id, created_at, updated_at "
            "FROM drawings WHERE slug = ?", (slug,)
        ).fetchone()
    if row is None:
        return None
    return {
        "slug": row[0],
        "name": row[1],
        "program": row[2],
        "source_id": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


def delete_drawing(slug: str) -> bool:
    with _lock:
        c = _connect()
        cur = c.execute("DELETE FROM drawings WHERE slug = ?", (slug,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# One-shot migration: import legacy user_drawings/*.cmd files (if any)
# ---------------------------------------------------------------------------

def import_legacy_files(legacy_dir: Path) -> int:
    """
    On first startup after switching to SQLite, sweep any leftover .cmd files
    from the pre-DB filesystem storage into the database. Idempotent.
    """
    if not legacy_dir.exists():
        return 0
    imported = 0
    for p in sorted(legacy_dir.glob("*.cmd")):
        slug = slugify(p.stem)
        # Skip if already in the DB
        if get_drawing(slug) is not None:
            continue
        program = p.read_text(encoding="utf-8")
        # Try to lift the original source_id from the header comment
        source_id: str | None = None
        for line in program.splitlines()[:5]:
            if line.startswith("# Forked from:"):
                source_id = line.split(":", 1)[1].strip()
                break
        save_drawing(name=p.stem, program=program, source_id=source_id)
        imported += 1
    return imported


__all__ = [
    "DB_PATH",
    "init",
    "slugify",
    "save_drawing",
    "list_drawings",
    "get_drawing",
    "delete_drawing",
    "import_legacy_files",
]
