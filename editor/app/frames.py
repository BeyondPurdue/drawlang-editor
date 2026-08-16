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
    """Apply schema + seed from legacy on-disk frames on first run.

    v0.8: also adds the ``owner_id`` column via ``ownership._apply_one``.
    """
    with _lock:
        _conn().executescript(SCHEMA)
    _seed_from_legacy_if_empty()
    try:
        from . import ownership as _ownership
        _ownership._apply_one("frames")
    except Exception:
        pass


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

def list_frames(owner_id: int | None = None, admin_id: int | None = None,
                source_owner_id: int | None = None) -> list[dict]:
    """Enumerate frames. Slim payload: id, name, source, field_count.

    v0.8: pass ``owner_id`` (and optionally ``admin_id`` for shared frames)
    to filter to that user's frames + admin-owned system frames.

    v0.8.1: pass ``source_owner_id`` (drawlang@ id) to also include the
    curator's frame set as read-only-visible-to-all showcase.
    """
    with _lock:
        if owner_id is None:
            rows = _conn().execute(
                "SELECT id, name, source, drawlang, fields_json, "
                "       created_at, updated_at "
                "FROM frames ORDER BY name"
            ).fetchall()
        else:
            allowed_ids = {int(owner_id)}
            if admin_id is not None:
                allowed_ids.add(int(admin_id))
            if source_owner_id is not None:
                allowed_ids.add(int(source_owner_id))
            placeholders = ",".join(["?"] * len(allowed_ids))
            rows = _conn().execute(
                f"SELECT id, name, source, drawlang, fields_json, "
                f"       created_at, updated_at "
                f"FROM frames WHERE owner_id IN ({placeholders}) "
                f"OR owner_id IS NULL ORDER BY name",
                tuple(allowed_ids),
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
    owner_id: int | None = None,
) -> dict:
    """Create a new frame. Raises ValueError on id collision.

    v0.8: `owner_id` stamps the row's ownership.
    """
    now = time.time()
    with _lock:
        c = _conn()
        existing = c.execute("SELECT id FROM frames WHERE id = ?",
                             (frame_id,)).fetchone()
        if existing:
            raise ValueError(f"frame id {frame_id!r} already exists")
        c.execute(
            "INSERT INTO frames (id, name, source, drawlang, fields_json, "
            " owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, name, source, drawlang,
             json.dumps(fields or []), owner_id, now, now),
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


def get_frame_owner(frame_id: str) -> int | None:
    """Return owner_id of a frame, or None if absent or unowned."""
    with _lock:
        row = _conn().execute(
            "SELECT owner_id FROM frames WHERE id = ?", (frame_id,)
        ).fetchone()
    if row is None:
        return None
    val = row[0]
    return int(val) if val is not None else None


# ---------------------------------------------------------------------------
# Cross-user copy & drawlang-native export/import
# ---------------------------------------------------------------------------

def list_frames_owned_by(owner_id: int) -> list[dict]:
    """Return the raw rows (name, source, drawlang, fields) owned strictly
    by ``owner_id`` — used by the seed-new-user and copy-to-user paths.
    """
    with _lock:
        rows = _conn().execute(
            "SELECT id, name, source, drawlang, fields_json, "
            "       created_at, updated_at "
            "FROM frames WHERE owner_id = ? ORDER BY name",
            (owner_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _unique_frame_id(base_id: str) -> str:
    """Return an id not present in the table. Tries ``base_id`` first, then
    ``base_id-2``, ``base_id-3``, … .  Used when copying between users to
    avoid stomping the target's existing frames.
    """
    with _lock:
        c = _conn()
        if c.execute("SELECT 1 FROM frames WHERE id = ?", (base_id,)).fetchone() is None:
            return base_id
        n = 2
        while True:
            cand = f"{base_id}-{n}"
            if c.execute("SELECT 1 FROM frames WHERE id = ?", (cand,)).fetchone() is None:
                return cand
            n += 1


def duplicate_frame(src_id: str, *, new_owner_id: int,
                    new_id: str | None = None) -> dict:
    """Deep-copy a frame row to ``new_owner_id``.

    - ``new_id``: forced id for the copy, must not collide. If None, we
      keep the source id when free, else append ``-2``/``-3``/… .
    Returns the newly created frame (composed view via ``get_frame``).
    """
    with _lock:
        row = _conn().execute(
            "SELECT id, name, source, drawlang, fields_json, "
            "       created_at, updated_at "
            "FROM frames WHERE id = ?",
            (src_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError(f"frame {src_id!r} not found")
    d = _row_to_dict(row)
    target_id = new_id or _unique_frame_id(src_id)
    return create_frame(
        frame_id=target_id,
        name=d["name"],
        drawlang=d["drawlang"],
        fields=d["fields"],
        source=d["source"],
        owner_id=new_owner_id,
    )


def seed_frames_for_user(new_user_id: int, source_owner_id: int) -> int:
    """Copy every frame owned by ``source_owner_id`` to ``new_user_id``.

    Used on user approval so each active account starts with the curated
    frame set maintained by the drawlang@ account.  Returns the number
    of frames copied.  Never raises; per-frame errors are swallowed so
    a single bad row cannot block user activation.
    """
    if new_user_id == source_owner_id:
        return 0
    n = 0
    for row in list_frames_owned_by(source_owner_id):
        try:
            target_id = _unique_frame_id(row["id"])
            create_frame(
                frame_id=target_id,
                name=row["name"],
                drawlang=row["drawlang"],
                fields=row["fields"],
                source=row["source"],
                owner_id=new_user_id,
            )
            n += 1
        except Exception:
            # Best-effort — a bad row must not block user activation.
            pass
    return n


# ---- Drawlang-native export / import --------------------------------------
#
# The frame's on-disk shape is a pair of files:
#
#   frames/<id>.drawlang         drawlang source
#   frames/<id>.fields.json      field metadata
#
# For a **single-file** transport that still speaks drawlang (no JSON on
# the wire), we serialise the frame as pure drawlang with a leading
# comment header that carries the metadata.  Comments are part of the
# drawlang grammar (line beginning with ``#``), so an exported frame is
# a valid drawlang program — no format invention.
#
# Grammar of the header (all lines start at column 0):
#
#   # @drawlang-frame v1
#   # @id <id>
#   # @name <name>
#   # @source <source-description-single-line>
#   # @field name=<n> desc=<d> editable=<0|1> line_index=<i> default=<v>
#   # @field ...
#   # @end-header
#   <ordinary drawlang program starts here>
#
# Escaping: within header values, we replace newlines with \n and
# backslash with \\ so each value stays single-line.  On import we
# reverse the escape.

_HDR_MAGIC = "# @drawlang-frame v1"
_HDR_END = "# @end-header"


def _hdr_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def _hdr_unescape(s: str) -> str:
    # Handles \\ and \n; anything else stays literal.
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n"); i += 2; continue
            if nxt == "\\":
                out.append("\\"); i += 2; continue
        out.append(ch); i += 1
    return "".join(out)


_KV_RE = re.compile(r"([a-z_][a-z0-9_]*)=(\"[^\"]*\"|\S+)", re.IGNORECASE)


def _parse_field_line(rest: str) -> dict:
    """Parse the payload of a `# @field ...` line into a field dict."""
    out: dict[str, Any] = {}
    for m in _KV_RE.finditer(rest):
        k = m.group(1).lower()
        raw = m.group(2)
        if raw.startswith('"') and raw.endswith('"'):
            v = _hdr_unescape(raw[1:-1])
        else:
            v = _hdr_unescape(raw)
        if k == "editable":
            out["editable"] = v in ("1", "true", "yes")
        elif k == "line_index":
            try:
                out["line_index"] = int(v)
            except ValueError:
                pass
        elif k == "desc":
            out["description"] = v
        else:
            out[k] = v
    return out


def export_drawlang(frame_id: str) -> str:
    """Serialise a frame to a single drawlang file (header + program).

    The result is valid drawlang: everything the header adds is comments.
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
    lines = [
        _HDR_MAGIC,
        f"# @id {_hdr_escape(d['id'])}",
        f"# @name {_hdr_escape(d['name'])}",
        f"# @source {_hdr_escape(d['source'])}",
    ]
    for f in d["fields"]:
        parts = [
            f'name={_hdr_escape(str(f.get("name","")))}',
            f'desc="{_hdr_escape(str(f.get("description","")))}"',
            f'editable={"1" if f.get("editable") else "0"}',
        ]
        if f.get("line_index") is not None:
            parts.append(f'line_index={int(f["line_index"])}')
        if f.get("default") is not None:
            parts.append(f'default="{_hdr_escape(str(f.get("default","")))}"')
        if f.get("x") is not None:
            parts.append(f'x={_hdr_escape(str(f.get("x")))}')
        if f.get("y") is not None:
            parts.append(f'y={_hdr_escape(str(f.get("y")))}')
        lines.append("# @field " + " ".join(parts))
    lines.append(_HDR_END)
    body = d["drawlang"] or ""
    if not body.endswith("\n"):
        body += "\n"
    return "\n".join(lines) + "\n" + body


def parse_exported(text: str) -> dict:
    """Parse a drawlang-native export back into an in-memory frame dict.

    Returns ``{id, name, source, drawlang, fields}``.  ``id`` may be
    empty if the file has no header — caller is responsible for choosing
    one in that case.  If the file lacks the magic header, the whole
    text is treated as the drawlang body with no metadata.
    """
    out = {"id": "", "name": "", "source": "", "drawlang": text, "fields": []}
    lines = text.split("\n")
    if not lines or lines[0].strip() != _HDR_MAGIC:
        return out
    i = 1
    fields: list[dict] = []
    while i < len(lines):
        line = lines[i].rstrip("\r")
        stripped = line.strip()
        if stripped == _HDR_END:
            i += 1
            break
        if stripped.startswith("# @id "):
            out["id"] = _hdr_unescape(stripped[len("# @id "):].strip())
        elif stripped.startswith("# @name "):
            out["name"] = _hdr_unescape(stripped[len("# @name "):].strip())
        elif stripped.startswith("# @source "):
            out["source"] = _hdr_unescape(stripped[len("# @source "):].strip())
        elif stripped.startswith("# @field "):
            fields.append(_parse_field_line(stripped[len("# @field "):]))
        # any other line before @end-header is ignored — future-compat.
        i += 1
    out["fields"] = fields
    out["drawlang"] = "\n".join(lines[i:])
    return out


def import_drawlang(text: str, *, owner_id: int,
                    forced_id: str | None = None) -> dict:
    """Create a frame from an exported drawlang file.

    - ``forced_id`` overrides the id from the header (useful when the
      caller wants to avoid a collision).  If neither is given the
      import raises ``ValueError``.
    - Id collisions are resolved by suffixing ``-2``/``-3``/… .
    """
    parsed = parse_exported(text)
    base_id = forced_id or parsed["id"]
    if not base_id:
        raise ValueError("exported frame is missing an id and none was supplied")
    if not re.match(r"^[A-Za-z0-9_-]+$", base_id):
        raise ValueError(f"invalid frame id {base_id!r}")
    target_id = _unique_frame_id(base_id)
    return create_frame(
        frame_id=target_id,
        name=parsed["name"] or target_id,
        drawlang=parsed["drawlang"] or "",
        fields=parsed["fields"],
        source=parsed["source"] or "",
        owner_id=owner_id,
    )


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
