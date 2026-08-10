"""
Library import — decodes tab-separated backup files into drawlang templates.

Backup file conventions:

- Records are separated by blank lines.
- Fields within a record are TAB-separated.
- Numeric fields are ASCII decimals, whitespace-padded.
- A `cmd` field is prefixed by its length in ASCII decimal, then the
  literal cmd text (no delimiter). Example: `103mr,-16,-16;...` means
  the cmd is 103 bytes starting after the "103".
- Multi-line cmd values continue across newlines inside the same record.

Schema:

- frame:  sheet border with a drawing area and grid ticks
- grid:   reference labels (A/B/C… rows, 1/2/3… columns) along a frame
- symbol: reusable graphical block (a named cmd program centered on 0,0)
- extsym: extended symbol (multi-segment cmd program, often frame guides)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Low-level record splitter
# ---------------------------------------------------------------------------


def iter_records(text: str) -> Iterator[list[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for chunk in re.split(r"\n\n+", text):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        joined = chunk.replace("\n", "")
        fields = [f.strip() for f in joined.split("\t")]
        yield fields


# ---------------------------------------------------------------------------
# cmd field extraction
# ---------------------------------------------------------------------------

CMD_PREFIX_RE = re.compile(r"^(\d+)(.*)$", re.DOTALL)


def extract_cmd(field: str) -> str | None:
    m = CMD_PREFIX_RE.match(field.strip())
    if not m:
        return None
    length = int(m.group(1))
    payload = m.group(2)
    if len(payload) < length:
        return payload
    return payload[:length]


# ---------------------------------------------------------------------------
# Table decoders
# ---------------------------------------------------------------------------


def parse_frame(text: str) -> list[dict]:
    """
    frame.csn columns:
        frm_id, pa_x, pa_y, pe_x, pe_y, gu_x, gu_y, go_x, go_y, ln_x, ln_y

    Semantics:
      frm_id    — frame id
      pa_x/pa_y — text position in left margin
      pe_x/pe_y — text position in right margin
      gu_x/gu_y — lower-left grid point (drawing-area lower-left, pixels)
      go_x/go_y — upper-right grid point (drawing-area upper-right, pixels)
      ln_x/ln_y — row/column spacing
    """
    rows = []
    for fields in iter_records(text):
        if len(fields) < 11:
            continue
        try:
            row = {
                "frm_id": int(fields[0]),
                "pa_x": int(fields[1]),
                "pa_y": int(fields[2]),
                "pe_x": int(fields[3]),
                "pe_y": int(fields[4]),
                "gu_x": int(fields[5]),
                "gu_y": int(fields[6]),
                "go_x": int(fields[7]),
                "go_y": int(fields[8]),
                "ln_x": int(fields[9]),
                "ln_y": int(fields[10]),
            }
        except (ValueError, IndexError):
            continue
        rows.append(row)
    return rows


def parse_raster(text: str) -> list[dict]:
    """
    grid.csn columns:
        frame_id, pro_id, spra, orient, titel, offset

    Field-format notes:
      spra    — 3-char language code (g1 = deutsch/DB, g2 = deutsch/editor,
                eng = englisch); may appear as e.g. "2g3" if the pro_id and
                spra got space-joined. We strip a leading digit.
      orient  — 1-char axis kind: 'x' (horizontal) or 'y' (vertical)
      titel   — 2-char grid label (A..F for y, 1..7 for x)
      offset  — pixel offset from origin (lower-left)
    """
    rows = []
    for fields in iter_records(text):
        if len(fields) < 6:
            continue
        # Strip leading digits from mixed cells
        def clean(s: str) -> str:
            return re.sub(r"^\d+", "", s).strip() or s

        try:
            row = {
                "frame_id": int(re.sub(r"\D", "", fields[0]) or "0"),
                "pro_id": int(re.sub(r"\D", "", fields[1]) or "0"),
                "spra": clean(fields[2]),
                "orient": clean(fields[3]),
                "label": clean(fields[4]),
                "offset": int(re.sub(r"\D", "", fields[5]) or "0"),
            }
        except (ValueError, IndexError):
            continue
        rows.append(row)
    return rows


def parse_pic_ex(text: str) -> list[dict]:
    """
    pic_ex.csn — extended symbols (multi-segment cmd programs).
    Rows share pic_id and are ordered by seq; concatenate all segments.
    """
    grouped: dict[int, dict[int, str]] = {}
    for fields in iter_records(text):
        if len(fields) < 3:
            continue
        try:
            pic_id = int(fields[0])
            seq = int(fields[1])
        except ValueError:
            continue
        cmd = extract_cmd(fields[2])
        if cmd is None:
            continue
        grouped.setdefault(pic_id, {})[seq] = cmd

    results = []
    for pic_id, segments in sorted(grouped.items()):
        parts = [segments[k] for k in sorted(segments.keys())]
        # Join segments defensively: if the previous segment does not end
        # with ';' (which happens when the source cmd_len prefix truncates
        # the payload mid-statement, e.g. `...dl,7,-2` on seq=N followed by
        # `mr,9,3;...` on seq=N+1), inserting a ';' prevents two opcodes
        # from being glued into an invalid statement like `dl,7,-2mr,9,3`.
        joined_parts: list[str] = []
        for i, part in enumerate(parts):
            if i > 0 and joined_parts and not joined_parts[-1].rstrip().endswith(";"):
                joined_parts.append(";")
            joined_parts.append(part)
        cmd_full = "".join(joined_parts)
        if not cmd_full.endswith(";"):
            cmd_full += ";"
        results.append({
            "pic_id": pic_id,
            "segments": len(segments),
            "cmd": cmd_full,
        })
    return results


def parse_pic_b(text: str) -> list[dict]:
    """
    pic_b.csn — symbol blocks. Column meanings (from inspection):
      col0=set, col1=block_id, col2=?, col3=?, col4=scale_float,
      col5=name/tag, col6=?, col7=?, col8=?,
      col9=width, col10=height, col11=?, col12=?, col13=cmd_with_prefix
    """
    rows = []
    for fields in iter_records(text):
        if len(fields) < 14:
            continue
        try:
            block_id = int(fields[1])
        except ValueError:
            continue
        name_raw = fields[5] if len(fields) > 5 else ""
        name = re.sub(r"^\d+", "", name_raw).strip() or f"block_{block_id}"
        try:
            width = int(fields[9])
            height = int(fields[10])
        except (ValueError, IndexError):
            width, height = None, None
        cmd = extract_cmd(fields[13]) if len(fields) > 13 else None
        if not cmd:
            continue
        rows.append({
            "block_id": block_id,
            "name": name,
            "width": width,
            "height": height,
            "cmd": cmd,
        })
    return rows


# ---------------------------------------------------------------------------
# Plan (obj_f) and placement (obj_g) decoders
# ---------------------------------------------------------------------------


def _strip_leading_digits(s: str) -> str:
    """Some ASCII-dump vch fields are space-padded so the first non-space run
    of digits from an adjacent numeric field may spill in. Strip leading
    decimal digits; fall back to the original if the result is empty.
    """
    stripped = re.sub(r"^\d+", "", s).strip()
    return stripped or s


def parse_obj_f(text: str) -> list[dict]:
    """
    obj_f.csn columns (from es680-damo/kap2_1/obj_f.htm):
        1  uas       c6     Plan type (YFR = FUP overview/detail)
        2  nam       vch20  Plan name (KKS tag)
        3  autor     vch15  Last-editor name
        4  datum     date   Last-edit timestamp
        5  uid       i4     Function-plan identifier (redundant)
        6  plan_id   i4     PRIMARY KEY, global
        7  loc_id    i2     Local id in parent plan
        8  frm_id    i2     Frame id
        9  max_se    i2     Number of pages
        10 max_lid   i2     Last-issued local id
        11 zust_fl   i2     Lock flag
        12 bp_fl     i1     OS/IS output flag
        13 pro_id    i2     Project id
        14 fkz_id    i2     Function-group id
        15 bez       vch40  Free-text description
        16 cpu_fl    i2     Multi-CPU flag
        17 awf       i4     Evaluation flag (temporary)
    """
    rows = []
    for fields in iter_records(text):
        if len(fields) < 9:
            continue
        try:
            uas = _strip_leading_digits(fields[0])
            nam = _strip_leading_digits(fields[1])
            row = {
                "uas": uas,
                "nam": nam,
                "plan_id": int(fields[5]),
                "loc_id": int(fields[6]),
                "frm_id": int(fields[7]),
                "max_se": int(fields[8]),
                "bez": fields[14] if len(fields) > 14 else "",
            }
        except (ValueError, IndexError):
            continue
        rows.append(row)
    return rows


def parse_obj_g(text: str) -> list[dict]:
    """
    obj_g.csn columns (from es680-damo/kap2_1/obj_g.htm):
        1  plan_id   i4    Plan owning this placement
        2  loc_id    i2    Local instance id
        3  pic_id    i2    pic_ex / pic_b identifier
        4  gid       i4    Sub-plan link (0 if leaf)
        5  po_x      i2    x-coordinate wrt plan origin
        6  po_y      i2    y-coordinate wrt plan origin
        7  se        i2    Page number
        8  ebene     i1    Visibility level
        9  dy_ea     i1    Dynamic-connector count
        10 cpu_fl    i4    CPU-mapping flag
        11-14 cpu1..cpu4 i2 target CPU ids
        15 fb_id     i2    Function-area id
        16 instanz_nr i2
        17 txp_id    i2
        18 awf       i4
        19 dyx_id    i4
        20 token_id  i4

    Real dumps carry 22 fields per record; extras are ignored.
    """
    rows = []
    for fields in iter_records(text):
        if len(fields) < 7:
            continue
        try:
            row = {
                "plan_id": int(fields[0]),
                "loc_id": int(fields[1]),
                "pic_id": int(fields[2]),
                "gid": int(fields[3]),
                "po_x": int(fields[4]),
                "po_y": int(fields[5]),
                "se": int(fields[6]),
            }
        except (ValueError, IndexError):
            continue
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Template composition — build drawlang programs from decoded rows
# ---------------------------------------------------------------------------


def frame_to_cmd(frame: dict, raster_rows: list[dict] | None = None) -> str:
    """
    Convert a frame row into a self-contained drawlang program that draws
    the drawing-area border plus optional grid tick labels around it.

    Uses gu_x/gu_y (lower-left) and go_x/go_y (upper-right) directly as
    absolute pixel coordinates — this is the coordinate system the source
    tables use, and pic_ex programs assume the same origin.
    """
    fid = frame["frm_id"]
    gu_x, gu_y = frame["gu_x"], frame["gu_y"]
    go_x, go_y = frame["go_x"], frame["go_y"]
    w = go_x - gu_x
    h = go_y - gu_y
    lines = [f"# Frame #{fid} — drawing area {w}x{h} px"]
    # Draw the drawing-area border
    lines.append(f"ma,{gu_x},{gu_y};")
    lines.append(f"rt,{w},{h};")
    # Title identifier at lower-left corner
    lines.append(f"ma,{gu_x + 8},{gu_y + 8};")
    lines.append(f"tz,10;")
    lines.append(f"tx,0.,Frame {fid};")

    if raster_rows:
        # Only rows matching this frame
        my_rasters = [r for r in raster_rows if r["frame_id"] == fid]
        if my_rasters:
            lines.append("")
            lines.append(f"# Grid labels ({len(my_rasters)} ticks)")
            for r in my_rasters:
                orient = r["orient"]
                label = r["label"]
                pos = r["offset"]
                if orient == "y":
                    # Y-axis label on left edge
                    lines.append(f"ma,{gu_x - 25},{pos};")
                    lines.append(f"dl,20,0;")
                    lines.append(f"ma,{gu_x - 18},{pos - 4};")
                    lines.append(f"tz,10;")
                    lines.append(f"tx,0.,{label};")
                elif orient == "x":
                    # X-axis label on bottom edge
                    lines.append(f"ma,{pos},{gu_y - 25};")
                    lines.append(f"dl,0,20;")
                    lines.append(f"ma,{pos - 4},{gu_y - 18};")
                    lines.append(f"tz,10;")
                    lines.append(f"tx,0.,{label};")
    return "\n".join(lines) + "\n"


def pic_ex_to_cmd(pic_ex_row: dict) -> str:
    """Return the assembled cmd program as-is — it is already drawlang."""
    return pic_ex_row["cmd"]


def pic_b_to_cmd(pic_b_row: dict) -> str:
    """
    pic_b programs typically use relative moves starting with negative
    offsets from the block's insertion point (center). Prepend an absolute
    anchor so the block is fully visible in a positive-coordinate viewport.
    """
    w = pic_b_row.get("width") or 64
    h = pic_b_row.get("height") or 64
    anchor_x = w + 20
    anchor_y = h + 20
    return f"ma,{anchor_x},{anchor_y};\n{pic_b_row['cmd']}"


def _is_stub_cmd(cmd: str) -> bool:
    """A pic_b cmd is a 'stub' (empty template) when its only pen instruction
    is a zero-distance move — the ES680 editor stores project-scope symbols
    (PROJPICT, etc.) with a 'mr,0,0;' body because their real content is
    injected per-project at draw time. Render these with a visible fallback.
    """
    if not cmd:
        return True
    # Strip whitespace and normalize; keep only non-comment statements
    stmts = [
        s.strip()
        for s in cmd.split(";")
        if s.strip() and not s.strip().startswith("#")
    ]
    if not stmts:
        return True
    # Only pen-move opcodes (mr, ma) with no drawing → stub
    return all(s.split(",")[0] in {"mr", "ma"} for s in stmts)


def _ensure_terminated(cmd: str) -> str:
    """Guarantee a cmd fragment ends with ';' so appending the next statement
    can't glue two opcodes together.

    A few source rows in the .csn dumps have cmd_len prefixes that truncate
    the payload mid-instruction (e.g. `...dl,-10` with no closing `;`). If we
    can't safely terminate (last token is a partial number-in-progress), drop
    the trailing incomplete fragment before adding `;`.
    """
    if not cmd:
        return ""
    stripped = cmd.rstrip()
    if not stripped:
        return ""
    if stripped.endswith(";"):
        return stripped
    # Try to salvage: cut the last unterminated fragment at the previous ';'
    last_semi = stripped.rfind(";")
    if last_semi >= 0:
        return stripped[: last_semi + 1]
    # No prior ';' at all — return empty rather than emit garbage
    return ""


def compose_plan_page(
    plan: dict,
    placements_on_page: list[dict],
    frames_by_id: dict[int, dict],
    pic_ex_by_id: dict[int, dict],
    pic_b_by_id: dict[int, dict],
    raster_rows: list[dict] | None = None,
) -> str:
    """
    Compose the full drawlang program for a single page of a plan.

    Steps:
      1. Emit the frame program (border + grid labels) for this plan's frm_id.
      2. For each obj_g placement on the page, emit an absolute anchor
         (ma,po_x,po_y) followed by the symbol's cmd program. Symbols are
         written in pen-relative style, so anchoring with `ma` positions them
         at the recorded plan coordinate.
      3. Every emitted symbol cmd is guaranteed to terminate with ';' so the
         next placement's 'ma' statement cannot merge into the previous one.
      4. Stub symbols (project-scope PROJPICT etc. stored as 'mr,0,0;') are
         rendered as a visible labeled marker so 17k+ placements that would
         otherwise be invisible show up on the drawing.

    Origin assumption: cmd coordinates share the frame's coordinate system
    (lower-left origin per drawlang spec, positive integers). po_x, po_y are
    interpreted directly as absolute drawlang coordinates. Empirical
    validation happens against the delivered PDFs.
    """
    lines = []
    lines.append(
        f"# Plan {plan.get('nam','?')} "
        f"(plan_id={plan['plan_id']}, frm_id={plan['frm_id']}, "
        f"page={placements_on_page[0]['se'] if placements_on_page else '?'})"
    )

    frame = frames_by_id.get(plan["frm_id"])
    if frame is not None:
        lines.append("")
        lines.append(f"# ---- frame #{plan['frm_id']} ----")
        lines.append(frame_to_cmd(frame, raster_rows).rstrip())

    lines.append("")
    lines.append(f"# ---- {len(placements_on_page)} placements ----")
    missing = 0
    stubbed = 0
    for pl in placements_on_page:
        pid = pl["pic_id"]
        po_x, po_y = pl["po_x"], pl["po_y"]
        sym = pic_ex_by_id.get(pid) or pic_b_by_id.get(pid)
        if sym is None:
            missing += 1
            # Draw a tiny marker so the placement is visible even without art
            lines.append(f"# pic_id {pid} not in library")
            lines.append(f"ma,{po_x},{po_y};ci,2;")
            continue
        cmd = _ensure_terminated(sym["cmd"])
        if _is_stub_cmd(cmd):
            # Project-scope stub — render a visible fallback so the placement
            # doesn't vanish. Small circle + short KKS-style label.
            stubbed += 1
            name = sym.get("name") or f"pic{pid}"
            # Sanitize label: strip characters that clash with the language
            label = str(name).replace(";", " ").replace(",", " ")[:16]
            lines.append(
                f"# loc_id={pl['loc_id']} pic_id={pid} STUB '{name}' at ({po_x},{po_y})"
            )
            lines.append(f"ma,{po_x},{po_y};")
            lines.append("ci,6;")
            lines.append("mr,8,-3;")
            lines.append("tz,7;")
            lines.append(f"tx,0.,{label};")
            continue
        lines.append(f"# loc_id={pl['loc_id']} pic_id={pid} at ({po_x},{po_y})")
        lines.append(f"ma,{po_x},{po_y};")
        lines.append(cmd)
    if missing:
        lines.append(
            f"# {missing} placement(s) reference symbols not present in the loaded library"
        )
    if stubbed:
        lines.append(
            f"# {stubbed} placement(s) use project-scope stub symbols (rendered as labeled markers)"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top-level: load a directory of CSN files and return template records
# ---------------------------------------------------------------------------


def load_templates(backup_dir: Path) -> dict:
    def read(name: str) -> str | None:
        p = backup_dir / name
        if not p.exists():
            return None
        return p.read_text(encoding="latin-1")

    result = {
        "frames": [], "rasters": [],
        "pic_ex": [], "pic_b": [],
        "plans": [], "placements": [],
    }
    if (t := read("frames.csn")) is not None:
        result["frames"] = parse_frame(t)
    if (t := read("grid.csn")) is not None:
        result["rasters"] = parse_raster(t)
    if (t := read("extended-symbols.csn")) is not None:
        result["pic_ex"] = parse_pic_ex(t)
    if (t := read("symbols.csn")) is not None:
        result["pic_b"] = parse_pic_b(t)
    if (t := read("plans.csn")) is not None:
        result["plans"] = parse_obj_f(t)
    if (t := read("placements.csn")) is not None:
        result["placements"] = parse_obj_g(t)
    return result


# ---------------------------------------------------------------------------
# Template catalog — turn decoded rows into editor entries with cmd programs
# ---------------------------------------------------------------------------


def build_catalog(data: dict) -> list[dict]:
    """
    Compose the templates catalog for the editor UI.

    Each entry has:
      id       — stable slug (used as example id)
      title    — human-readable label
      category — "Frames" | "Symbols" | "Frame guides" | "Extended symbols"
      program  — drawlang cmd string, editor-loadable
      source   — reference to the DB record (for later save-back)
    """
    catalog = []

    # 1. Frames (with attached raster labels)
    for frame in data["frames"]:
        fid = frame["frm_id"]
        catalog.append({
            "id": f"frame-{fid}",
            "title": f"Frame #{fid} ({frame['go_x'] - frame['gu_x']}x{frame['go_y'] - frame['gu_y']})",
            "category": "Frames",
            "program": frame_to_cmd(frame, data["rasters"]),
            "source": {"table": "frame", "frm_id": fid},
        })

    # 2. pic_ex (frame chrome — rulers, axis scales, title-block decorations)
    #    These are the extended symbols, often used as reusable frame guides.
    for row in data["pic_ex"]:
        pid = row["pic_id"]
        cat = "Frame guides" if pid < 0 else "Extended symbols"
        catalog.append({
            "id": f"picex-{pid}",
            "title": f"pic_ex {pid} ({row['segments']} seg)",
            "category": cat,
            "program": pic_ex_to_cmd(row),
            "source": {"table": "pic_ex", "pic_id": pid},
        })

    # 3. pic_b (symbol blocks — the symbol library)
    for row in data["pic_b"]:
        catalog.append({
            "id": f"picb-{row['block_id']}",
            "title": f"{row['name']} ({row['width']}x{row['height']})",
            "category": "Symbols",
            "program": pic_b_to_cmd(row),
            "source": {"table": "pic_b", "block_id": row["block_id"]},
        })

    return catalog
