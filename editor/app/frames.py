"""
Frames — DB-backed editable frame templates (v0.7).

Prior to v0.7 the frames lived as a pair of files on disk:

    frames/<id>.drawlang        # drawlang source with placeholder tx lines
    frames/<id>.fields.json     # field metadata + line indices

That was fine for read-only starter templates but the user has been
clear that frames must be **editable and creatable at runtime**. So the
storage is now a SQLite table with the same shape and API, and the
existing on-disk frames are seeded into the table on first init.

Public API is unchanged so the rest of the app (canvases, render
endpoint, etc.) keeps working without edits:

- ``list_frames()`` — enumerate.
- ``get_frame(frame_id, values=None)`` — compose with editable values applied.
- New: ``create_frame(...)``, ``update_frame(...)``, ``delete_frame(...)``.

The DrawLang language layer is **not** touched by this file.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import storage as _storage


# ---------------------------------------------------------------------------
# Legacy on-disk location (for one-time seed migration)
# ---------------------------------------------------------------------------

# NOTE: not deleted after migration; the files stay in the repo for
# reference and reproducibility but the runtime source of truth is
# whatever is in the DB. If you edit a frame in the UI, the DB row wins.
LEGACY_FRAMES_DIR = Path(__file__).resolve().parent.parent.parent / "frames"

# Back-compat alias (older tests may still import FRAMES_DIR)
FRAMES_DIR = LEGACY_FRAMES_DIR


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT '',
    drawlang     TEXT NOT NULL,
    fields_json  TEXT NOT NULL DEFAULT '[]',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
"""


_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return _storage._connect()


def init() -> None:
    """Apply schema + seed from legacy on-disk frames on first run."""
    with _lock:
        _conn().executescript(SCHEMA)
    _seed_from_legacy_if_empty()


def _seed_from_legacy_if_empty() -> None:
    with _lock:
        n = _conn().execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    if n > 0:
        return
    if not LEGACY_FRAMES_DIR.exists():
        return
    now = time.time()
    with _lock:
        c = _conn()
        for dl in sorted(LEGACY_FRAMES_DIR.glob("*.drawlang")):
            frame_id = dl.stem
            fields_path = LEGACY_FRAMES_DIR / f"{frame_id}.fields.json"
            source = dl.read_text()
            meta: dict[str, Any] = {"fields": []}
            if fields_path.exists():
                try:
                    meta = json.loads(fields_path.read_text())
                except Exception:
                    meta = {"fields": []}
            c.execute(
                "INSERT OR IGNORE INTO frames "
                "(id, name, source, drawlang, fields_json, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    frame_id,
                    meta.get("name", frame_id),
                    meta.get("source", ""),
                    source,
                    json.dumps(meta.get("fields", [])),
                    now,
                    now,
                ),
            )


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: tuple) -> dict:
    fid, name, source, dl, fields_json, ca, ua = row
    try:
        fields = json.loads(fields_json)
    except Exception:
        fields = []
    return {
        "id": fid,
        "name": name,
        "source": source,
        "drawlang": dl,
        "fields": fields,
        "field_count": sum(1 for f in fields if f.get("editable", False)),
        "created_at": ca,
        "updated_at": ua,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_frames() -> list[dict]:
    """Enumerate frames. Slim payload: id, name, source, field_count."""
    with _lock:
        rows = _conn().execute(
            "SELECT id, name, source, drawlang, fields_json, "
            "       created_at, updated_at "
            "FROM frames ORDER BY name"
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        # Legacy shape expected by existing UI: {id, source, field_count}
        out.append({
            "id": d["id"],
            "name": d["name"],
            "source": d["source"],
            "field_count": d["field_count"],
        })
    return out


def get_frame(frame_id: str, values: dict[str, str] | None = None) -> dict:
    """
    Return the frame's composed drawlang + field metadata.

    ``values`` is a dict {field_name: value}. Only editable fields are applied.
    Compatible with the pre-v0.7 file-backed shape.
    """
    with _lock:
        row = _conn().execute(
            "SELECT id, name, source, drawlang, fields_json, "
            "       created_at, updated_at "
            "FROM frames WHERE id = ?",
            (frame_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"frame {frame_id!r} not found")
    d = _row_to_dict(row)
    fields = d["fields"]
    values = values or {}
    applied_source = _apply_values(d["drawlang"], fields, values)
    field_info = []
    for f in fields:
        if not f.get("editable", False):
            continue
        current = values.get(f["name"], f.get("default", ""))
        field_info.append({
            "name": f["name"],
            "description": f.get("description", ""),
            "x": f.get("x"),
            "y": f.get("y"),
            "value": current,
        })
    return {
        "id": d["id"],
        "name": d["name"],
        "source": d["source"],
        "drawlang": applied_source,
        "fields": field_info,
    }


def create_frame(
    frame_id: str,
    name: str,
    drawlang: str,
    fields: list[dict] | None = None,
    source: str = "",
) -> dict:
    """Create a new frame. Raises ValueError on id collision."""
    now = time.time()
    with _lock:
        c = _conn()
        existing = c.execute("SELECT id FROM frames WHERE id = ?",
                             (frame_id,)).fetchone()
        if existing:
            raise ValueError(f"frame id {frame_id!r} already exists")
        c.execute(
            "INSERT INTO frames (id, name, source, drawlang, fields_json, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (frame_id, name, source, drawlang,
             json.dumps(fields or []), now, now),
        )
    return get_frame(frame_id)


def update_frame(
    frame_id: str,
    *,
    name: str | None = None,
    drawlang: str | None = None,
    fields: list[dict] | None = None,
    source: str | None = None,
) -> dict:
    """Patch a frame. Any argument left as None is preserved."""
    now = time.time()
    with _lock:
        c = _conn()
        row = c.execute("SELECT id FROM frames WHERE id = ?",
                        (frame_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(f"frame {frame_id!r} not found")
        sets, args = [], []
        if name is not None:
            sets.append("name = ?"); args.append(name)
        if drawlang is not None:
            sets.append("drawlang = ?"); args.append(drawlang)
        if fields is not None:
            sets.append("fields_json = ?"); args.append(json.dumps(fields))
        if source is not None:
            sets.append("source = ?"); args.append(source)
        sets.append("updated_at = ?"); args.append(now)
        args.append(frame_id)
        c.execute(f"UPDATE frames SET {', '.join(sets)} WHERE id = ?", args)
    return get_frame(frame_id)


def delete_frame(frame_id: str) -> bool:
    with _lock:
        c = _conn()
        cur = c.execute("DELETE FROM frames WHERE id = ?", (frame_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Value application (unchanged from v0.6)
# ---------------------------------------------------------------------------

TX_LINE_RE = re.compile(r"^(tx,[^,]+,)(.*)(;)\s*$")


def _apply_values(source: str, fields: list[dict],
                  values: dict[str, str]) -> str:
    """Rewrite tx lines in ``source`` at the line indices in ``fields``."""
    by_line: dict[int, str] = {}
    for f in fields:
        if not f.get("editable", False):
            continue
        name = f["name"]
        if name in values:
            by_line[f["line_index"]] = values[name]

    if not by_line:
        return source

    lines = source.split("\n")
    content_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        content_idx += 1
        if content_idx in by_line:
            val = by_line[content_idx]
            m = TX_LINE_RE.match(stripped)
            if m:
                prefix, _, semi = m.group(1), m.group(2), m.group(3)
                safe = val.replace(";", "").replace(",", " ")
                lines[i] = f"{prefix}{safe}{semi}"
    return "\n".join(lines)
