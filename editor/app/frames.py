"""
ES680 frame templates with editable title-block fields.

A "frame" is a drawlang source file plus a field map. The field map lists
every editable text slot (name, coordinate, description, default). Values are
applied by rewriting the specific `tx,...,` statements at the given
line indices in the source drawlang.

This module owns the source-of-truth for frames. All edits go through the API,
never client-side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


FRAMES_DIR = Path(__file__).resolve().parent.parent.parent / "frames"


def _load_frame_source(frame_id: str) -> tuple[str, dict]:
    """Load raw drawlang + field map for a frame id."""
    dl_path = FRAMES_DIR / f"{frame_id}.drawlang"
    fields_path = FRAMES_DIR / f"{frame_id}.fields.json"
    if not dl_path.exists():
        raise FileNotFoundError(f"frame {frame_id!r} not found")
    source = dl_path.read_text()
    fields_meta: dict[str, Any] = {"fields": []}
    if fields_path.exists():
        fields_meta = json.loads(fields_path.read_text())
    return source, fields_meta


def list_frames() -> list[dict]:
    """Enumerate available frames."""
    out = []
    if not FRAMES_DIR.exists():
        return out
    for dl in sorted(FRAMES_DIR.glob("*.drawlang")):
        frame_id = dl.stem
        try:
            _, meta = _load_frame_source(frame_id)
        except Exception:
            meta = {}
        out.append({
            "id": frame_id,
            "source": meta.get("source", ""),
            "field_count": len(meta.get("fields", [])),
        })
    return out


def get_frame(frame_id: str, values: dict[str, str] | None = None) -> dict:
    """
    Return the frame's composed drawlang, its field metadata,
    and the values-applied render input.

    `values` is a dict {field_name: value}. Only editable fields are applied.
    """
    source, meta = _load_frame_source(frame_id)
    fields = meta.get("fields", [])
    values = values or {}

    # Apply values: for each editable field with a value, rewrite the tx line
    # at its line_index. Non-editable fields keep their source text.
    applied_source = _apply_values(source, fields, values)

    # Build UI-friendly field list with current values
    field_info = []
    for f in fields:
        if not f.get("editable", False):
            continue
        current = values.get(f["name"], f.get("default", ""))
        field_info.append({
            "name": f["name"],
            "description": f.get("description", ""),
            "x": f["x"],
            "y": f["y"],
            "value": current,
        })

    return {
        "id": frame_id,
        "source": meta.get("source", ""),
        "drawlang": applied_source,
        "fields": field_info,
    }


TX_LINE_RE = re.compile(r"^(tx,[^,]+,)(.*)(;)\s*$")


def _apply_values(source: str, fields: list[dict], values: dict[str, str]) -> str:
    """
    Rewrite tx lines in `source` at the line indices in `fields`.

    Line indices in the field map are 0-based indices into the STRIPPED
    non-blank, non-comment content. We compute the same index while walking
    the source so we can find the exact line to rewrite.
    """
    # Build map: line_index -> value_to_apply
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
    # The field_map was built against the RAW extracted list (no comments/blanks).
    # So we walk `lines`, skip blanks/comments, count "content" lines, and rewrite
    # the corresponding line when its content index matches.
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
                # Escape any semicolons/commas in the value defensively
                safe = val.replace(";", "").replace(",", " ")
                lines[i] = f"{prefix}{safe}{semi}"
    return "\n".join(lines)
