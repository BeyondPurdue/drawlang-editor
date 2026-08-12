"""
Drawing Language v0.1 — Web Editor

FastAPI backend serving:
  GET  /                     -> the editor SPA
  POST /render               -> {program, backend} -> {svg | ps | error}
  POST /export/pdf           -> {program} -> PDF bytes (via ps2pdf)
  GET  /examples             -> list of example programs (from spec §12)
  GET  /reference            -> opcode + modifier quick reference

The backend is a thin shim over the drawlang package. All drawing logic
lives in the interpreter — the editor knows nothing about opcodes.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the drawlang package importable when running from the repo root
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from drawlang import SPEC_VERSION, render  # noqa: E402
from drawlang.errors import DrawLangError  # noqa: E402

from app.import_library import (  # noqa: E402
    load_templates,
    build_catalog,
    compose_plan_page,
)
from app import storage  # noqa: E402
from app import canvases as _canvases  # noqa: E402
from app import library as _library  # noqa: E402
from app import tagged_svg as _tagged  # noqa: E402  (v0.7 editor tagging)


app = FastAPI(title="Drawing Language Editor", version=SPEC_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _init_storage() -> None:
    storage.init()
    _canvases.init()
    _library.init()
    # v0.7: frames are DB-backed. init() applies schema and seeds from
    # legacy on-disk frames on first run.
    from app import frames as _frames_init
    _frames_init.init()
    # Sweep any pre-DB filesystem drawings into the DB, once.
    legacy = Path(__file__).resolve().parent.parent / "user_drawings"
    imported = storage.import_legacy_files(legacy)
    if imported:
        print(f"[storage] imported {imported} legacy drawing(s) from {legacy}")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _read_git_sha() -> str:
    """Best-effort read of the deployed commit SHA. Never raises."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


_GIT_SHA_CACHE = _read_git_sha()


@app.get("/health")
def health() -> dict:
    """Deployment health probe. Reports package version, spec version, and
    the deployed git SHA so that after a `git pull` we can confirm the new
    code is actually live without ssh access.
    """
    try:
        from drawlang import __version__ as pkg_version
    except Exception:
        pkg_version = "unknown"
    return {
        "status": "ok",
        "spec_version": SPEC_VERSION,
        "drawlang_version": pkg_version,
        "semantic_layer": "0.7.6.1",  # v0.7.6.1 Toolbar visual cleanup (grammar frozen at v0.6)
        "git_sha": _GIT_SHA_CACHE,
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RenderRequest(BaseModel):
    program: str
    backend: str = "svg"  # "svg" or "ps"


class RenderResponse(BaseModel):
    ok: bool
    output: str | None = None
    error: str | None = None
    error_kind: str | None = None
    statement_index: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Canvas editor is the default landing page. Old v0.1 index lives at /legacy.
    return HTMLResponse((STATIC_DIR / "canvas-editor.html").read_text(encoding="utf-8"))


@app.get("/legacy", response_class=HTMLResponse)
def legacy_index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/canvas-editor", response_class=HTMLResponse)
def canvas_editor_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "canvas-editor.html").read_text(encoding="utf-8"))


@app.get("/library", response_class=HTMLResponse)
def library_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "library.html").read_text(encoding="utf-8"))


@app.get("/frames-editor", response_class=HTMLResponse)
def frames_editor_page() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "frames-editor.html").read_text(encoding="utf-8"))


@app.post("/render", response_model=RenderResponse)
def render_program(req: RenderRequest) -> RenderResponse:
    if req.backend not in ("svg", "ps"):
        raise HTTPException(400, f"unknown backend: {req.backend}")
    try:
        output = render(req.program, req.backend)
        return RenderResponse(ok=True, output=output)
    except DrawLangError as e:
        return RenderResponse(
            ok=False,
            error=str(e),
            error_kind=type(e).__name__,
            statement_index=getattr(e, "statement_index", None),
        )
    except Exception as e:  # unexpected — surface but don't crash
        return RenderResponse(
            ok=False, error=f"internal error: {e}", error_kind="Internal"
        )


import re as _re_export


@app.post("/export/pdf")
def export_pdf(req: RenderRequest) -> Response:
    """Render the program to PostScript, then convert to PDF via ps2pdf.

    Sizes the PDF page to the actual %%BoundingBox from the PS output so
    landscape frames (A3) don't get clipped by the default Letter page.
    """
    try:
        ps = render(req.program, "ps")
    except DrawLangError as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

    # Parse %%BoundingBox to size the output page
    bbox_m = _re_export.search(
        r"%%BoundingBox:\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
        ps,
    )
    if bbox_m:
        llx, lly, urx, ury = (float(bbox_m.group(i)) for i in range(1, 5))
        pad = 10.0
        page_w = max(int(urx - llx + 2 * pad), 100)
        page_h = max(int(ury - lly + 2 * pad), 100)
        # Also shift origin so content lands at (pad, pad)
        prelude = f"<< /PageSize [{page_w} {page_h}] >> setpagedevice\n"
        prelude += f"{-llx + pad} {-lly + pad} translate\n"
    else:
        page_w = page_h = 0
        prelude = ""

    with tempfile.TemporaryDirectory() as td:
        ps_path = Path(td) / "drawing.ps"
        pdf_path = Path(td) / "drawing.pdf"
        # Inject the page setup right after the %%EndComments marker
        if prelude:
            marker = "%%EndComments\n"
            idx = ps.find(marker)
            if idx >= 0:
                ps_out = ps[: idx + len(marker)] + prelude + ps[idx + len(marker) :]
            else:
                ps_out = prelude + ps
        else:
            ps_out = ps
        ps_path.write_text(ps_out, encoding="ascii")
        cmd = ["ps2pdf"]
        if page_w and page_h:
            cmd += [f"-dDEVICEWIDTHPOINTS={page_w}", f"-dDEVICEHEIGHTPOINTS={page_h}"]
        cmd += [str(ps_path), str(pdf_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(
                500, f"ps2pdf failed: {result.stderr or result.stdout}"
            )
        return Response(
            content=pdf_path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="drawing.pdf"'},
        )


@app.get("/examples")
def examples() -> JSONResponse:
    """
    Returns the merged list of built-in examples (spec §12) and imported
    Library templates (frames, symbols, frame guides) imported at startup.
    Each entry has a `category` field for filtering.
    """
    return JSONResponse(_EXAMPLES_MERGED)


@app.get("/reference")
def reference() -> JSONResponse:
    return JSONResponse(REFERENCE)


# ---------------------------------------------------------------------------
# User drawings — save edited templates back to the project's user_drawings/
# ---------------------------------------------------------------------------


class SaveRequest(BaseModel):
    name: str
    program: str
    source_id: str | None = None  # e.g. 'frame-1' or 'picb-3204' if forked


@app.post("/save")
def save_drawing(req: SaveRequest) -> JSONResponse:
    """
    Persist an edited program as a database row.

    Name is slugified into a stable id; re-saving the same name updates
    the existing row. The library templates remain read-only; user rows
    live in the `drawings` table.
    """
    result = storage.save_drawing(
        name=req.name,
        program=req.program,
        source_id=req.source_id,
    )
    return JSONResponse(result)


@app.get("/drawings")
def list_drawings() -> JSONResponse:
    """List all saved user drawings from the database."""
    return JSONResponse(storage.list_drawings())


@app.delete("/drawings/{slug}")
def delete_drawing(slug: str) -> JSONResponse:
    deleted = storage.delete_drawing(slug)
    return JSONResponse({"ok": deleted, "slug": slug})


# ---------------------------------------------------------------------------
# Example library — mirrors spec §12
# ---------------------------------------------------------------------------


EXAMPLES = [
    {
        "id": "blank",
        "title": "Blank canvas",
        "description": "Start writing your own program.",
        "category": "Examples",
        "program": "ma,50,50;\n",
    },
    {
        "id": "12.1",
        "title": "§12.1 — Rectangle with diagonal",
        "description": "Move to (10,10), draw an 80×40 rectangle, then a diagonal line across it.",
        "category": "Examples",
        "program": "ma,10,10;\nrt,80,40;\ndl,80,40;\n",
    },
    {
        "id": "12.2",
        "title": "§12.2 — Crosshair marker",
        "description": "Two intersecting lines centered on a point.",
        "category": "Examples",
        "program": "ma,100,100;\nmr,-10,0; dl,20,0;\nmr,-10,-10; dl,0,20;\n",
    },
    {
        "id": "12.3",
        "title": "§12.3 — Filled bullet with label",
        "description": "Filled circle + text label at a right-offset position.",
        "category": "Examples",
        "program": "ma,50,50;\nci,3,f;\nmr,8,-4;\ntz,10;\ntx,0.,Bohemia Market;\n",
    },
    {
        "id": "12.4",
        "title": "§12.4 — Quarter arc",
        "description": "Arc starting at 90°, sweeping 90° counterclockwise.",
        "category": "Examples",
        "program": "ma,100,100;\nar,20,90.,90.;\n",
    },
    {
        "id": "12.5",
        "title": "§12.5 — Smooth Catmull-Rom curve",
        "description": "Spline through four anchors → three Bézier segments.",
        "category": "Examples",
        "program": "sp,0,0,30,50,80,50,120,0;\n",
    },
    {
        "id": "12.6",
        "title": "§12.6 — Block with photo inset",
        "description": "Container rectangle, image placeholder, and caption text.",
        "category": "Examples",
        "program": (
            "ma,10,10; rt,200,150;\n"
            "ma,20,20; im,180,100,7;\n"
            "ma,20,130; tz,12; tx,0.,PID Section A;\n"
        ),
    },
    {
        "id": "12.7",
        "title": "§12.7 — Dashed reference line",
        "description": "Horizontal reference line with dashed styling.",
        "category": "Examples",
        "program": "ma,0,50;\ndl,300,0,d;\n",
    },
    {
        "id": "12.8",
        "title": "§12.8 — atmend (invisible boundary)",
        "description": "Invisible rectangle marks the bounding box; text is placed inside.",
        "category": "Examples",
        "program": "ma,0,0;\nrt,100,50,i;\nma,10,10;\ntx,0.,Content;\n",
    },
    {
        "id": "combined",
        "title": "Combined — all opcodes, all examples",
        "description": "Every worked example composed into one drawing.",
        "category": "Examples",
        "program": (
            "ma,10,10; rt,80,40; dl,80,40;\n"
            "ma,150,50; mr,-10,0; dl,20,0; mr,-10,-10; dl,0,20;\n"
            "ma,220,50; ci,3,f; mr,8,-4; tz,10; tx,0.,Bohemia Market;\n"
            "ma,400,50; ar,20,90.,90.;\n"
            "sp,10,150,60,220,150,220,220,150;\n"
            "ma,10,300; rt,200,100; ma,20,320; im,180,60,7;\n"
            "ma,20,390; tz,12; tx,0.,PID Section A;\n"
            "ma,300,300; dl,150,0,d;\n"
        ),
    },
    {
        "id": "colors",
        "title": "Palette showcase — color modifier",
        "description": "Every color index in the default palette.",
        "category": "Examples",
        "program": (
            "ma,20,50; ci,15,f,c0;\n"
            "ma,60,50; ci,15,f,c1;\n"
            "ma,100,50; ci,15,f,c2;\n"
            "ma,140,50; ci,15,f,c3;\n"
            "ma,180,50; ci,15,f,c4;\n"
            "ma,220,50; ci,15,f,c5;\n"
            "ma,260,50; ci,15,f,c6;\n"
            "ma,300,50; ci,15,f,c7;\n"
        ),
    },
]


# ---------------------------------------------------------------------------
# Library template import — merged into EXAMPLES with category tags
# ---------------------------------------------------------------------------


def _load_library_data() -> dict:
    """Load raw parsed library data from ../library-data/*.csn."""
    data_dir = Path(__file__).resolve().parent.parent / "library-data"
    if not data_dir.exists():
        return {}
    try:
        return load_templates(data_dir)
    except Exception:
        return {}


def _library_catalog(data: dict) -> list[dict]:
    try:
        catalog = build_catalog(data)
    except Exception:
        return []
    for entry in catalog:
        entry["description"] = f"Imported from library ({entry['source']['table']})."
    return catalog


# Load once at startup; used by /examples, /api/plans, /api/plans/{id}.
_LIBRARY_DATA = _load_library_data()
_LIBRARY_TEMPLATES = _library_catalog(_LIBRARY_DATA)

# ---------------------------------------------------------------------------
# Plan (obj_f/obj_g) composition endpoints
# ---------------------------------------------------------------------------

_PLANS = _LIBRARY_DATA.get("plans", [])
_PLACEMENTS = _LIBRARY_DATA.get("placements", [])
_FRAMES_BY_ID = {f["frm_id"]: f for f in _LIBRARY_DATA.get("frames", [])}
_PIC_EX_BY_ID = {r["pic_id"]: r for r in _LIBRARY_DATA.get("pic_ex", [])}
_PIC_B_BY_ID = {r["block_id"]: r for r in _LIBRARY_DATA.get("pic_b", [])}
_RASTERS = _LIBRARY_DATA.get("rasters", [])

# Precompute per-plan placement groups: {plan_id: {se: [placement,...]}}
_PLAN_PLACEMENTS: dict[int, dict[int, list[dict]]] = {}
for _pl in _PLACEMENTS:
    _PLAN_PLACEMENTS.setdefault(_pl["plan_id"], {}).setdefault(_pl["se"], []).append(_pl)

_PLANS_BY_ID = {p["plan_id"]: p for p in _PLANS}


def _plan_pages(plan_id: int) -> list[int]:
    pages = _PLAN_PLACEMENTS.get(plan_id, {})
    if pages:
        return sorted(pages.keys())
    plan = _PLANS_BY_ID.get(plan_id)
    if plan is None:
        return []
    n = max(1, plan.get("max_se", 1))
    return list(range(1, n + 1))


_PLAN_INDEX_CACHE: list[dict] | None = None


def _plan_index_entries() -> list[dict]:
    """Lightweight index entries for the /examples sidebar. Program is a
    placeholder — the frontend fetches the real composed program via
    /api/plans/{id}?page=N when the entry is clicked."""
    global _PLAN_INDEX_CACHE
    if _PLAN_INDEX_CACHE is not None:
        return _PLAN_INDEX_CACHE
    entries = []
    for plan in _PLANS:
        pages = _plan_pages(plan["plan_id"])
        n_symbols = sum(len(v) for v in _PLAN_PLACEMENTS.get(plan["plan_id"], {}).values())
        for se in pages:
            page_count = len(_PLAN_PLACEMENTS.get(plan["plan_id"], {}).get(se, []))
            page_tag = f" p{se}" if len(pages) > 1 else ""
            entries.append({
                "id": f"plan-{plan['plan_id']}-{se}",
                "title": f"{plan['nam']}{page_tag} ({page_count} sym)",
                "description": (
                    f"Plan {plan['plan_id']} • uas={plan['uas']} • "
                    f"frame #{plan['frm_id']} • page {se}/{len(pages)} • "
                    f"{page_count} of {n_symbols} placements"
                ),
                "category": "Plans",
                "program": f"# Loading plan {plan['nam']} page {se}…",
                "lazy": True,
                "plan_id": plan["plan_id"],
                "page": se,
                "source": {"table": "obj_f", "plan_id": plan["plan_id"], "page": se},
            })
    _PLAN_INDEX_CACHE = entries
    return entries


@app.get("/api/plans")
def list_plans() -> JSONResponse:
    """Return a compact list of plan-page entries (id, title, page count)."""
    return JSONResponse(_plan_index_entries())


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: int, page: int = 1) -> JSONResponse:
    """Return the composed drawlang program for one page of a plan."""
    plan = _PLANS_BY_ID.get(plan_id)
    if plan is None:
        raise HTTPException(404, f"plan {plan_id} not found")
    pages = _PLAN_PLACEMENTS.get(plan_id, {})
    placements = pages.get(page, [])
    program = compose_plan_page(
        plan=plan,
        placements_on_page=placements,
        frames_by_id=_FRAMES_BY_ID,
        pic_ex_by_id=_PIC_EX_BY_ID,
        pic_b_by_id=_PIC_B_BY_ID,
        raster_rows=_RASTERS,
    )
    return JSONResponse({
        "plan_id": plan_id,
        "page": page,
        "pages": _plan_pages(plan_id),
        "nam": plan.get("nam"),
        "frm_id": plan.get("frm_id"),
        "placement_count": len(placements),
        "program": program,
    })


# Plans are NOT merged into /examples — they're fetched lazily by the
# frontend via /api/plans when the user activates the "Plans" category tag.
# This keeps the /examples payload under ~1 MB even with 17k plan pages.
_EXAMPLES_MERGED = EXAMPLES + _LIBRARY_TEMPLATES


# ---------------------------------------------------------------------------
# Reference — pulled from spec §6, §7, §8
# ---------------------------------------------------------------------------


REFERENCE = {
    "spec_version": SPEC_VERSION,
    "core_opcodes": [
        {"op": "mr", "signature": "mr,dx,dy", "desc": "Move pen relative. Updates pen position."},
        {"op": "ma", "signature": "ma,x,y", "desc": "Move pen absolute. Updates pen position."},
        {"op": "dl", "signature": "dl,dx,dy", "desc": "Draw line relative from pen to (x+dx, y+dy). Pen advances to endpoint."},
        {"op": "rt", "signature": "rt,w,h[,f][,i][,d][,c<n>]", "desc": "Rectangle at pen. Pen unchanged."},
        {"op": "ci", "signature": "ci,r[,f][,d][,c<n>]", "desc": "Circle centered at pen. Pen unchanged."},
        {"op": "tz", "signature": "tz,size", "desc": "Set text size. Pen unchanged."},
        {"op": "tx", "signature": "tx,angle,string[,c<n>]", "desc": "Draw text at pen, rotated by angle°. Pen unchanged. Angle is a float (with '.')."},
    ],
    "extension_opcodes": [
        {"op": "ar", "signature": "ar,r,start,sweep[,f][,d][,c<n>]", "desc": "Arc centered at pen. start/sweep are floats in degrees, CCW positive."},
        {"op": "bz", "signature": "bz,dx1,dy1,dx2,dy2,dx3,dy3[,d][,c<n>]", "desc": "Cubic Bézier from pen using 3 relative control points. Pen advances to P3."},
        {"op": "sp", "signature": "sp,x1,y1,...,xN,yN[,d][,c<n>]", "desc": "Spline (Catmull-Rom, tension 0.5) through N absolute anchor points. Pen advances to last anchor."},
        {"op": "im", "signature": "im,w,h,image_id", "desc": "Place image (foreign key to img table) at pen with given w×h. Pen unchanged."},
    ],
    "modifiers": [
        {"mod": ",f", "desc": "Fill (rt, ci, ar, sp only)."},
        {"mod": ",i", "desc": "Invisible / atmend — bounding box only, no visible mark (rt only)."},
        {"mod": ",d", "desc": "Dashed stroke."},
        {"mod": ",c<n>", "desc": "Color palette index (non-negative integer). Example: c3 = index 3."},
    ],
    "coord_system": "y-up Cartesian. Origin lower-left. Angles CCW in degrees, 0° along +X.",
    "pen_state": "Position (x, y) + text_size (initial 10). Implicit pen-up between statements.",
}


# ---------------------------------------------------------------------------
# Frame templates API — editable legacy title-block frames
# ---------------------------------------------------------------------------
from app import frames as _frames_mod  # noqa: E402


@app.get("/api/frames")
def api_list_frames() -> JSONResponse:
    """List available frame templates."""
    return JSONResponse({"frames": _frames_mod.list_frames()})


@app.get("/api/frames/{frame_id}")
def api_get_frame(frame_id: str) -> JSONResponse:
    """Return frame drawlang + field metadata (no user values applied)."""
    try:
        return JSONResponse(_frames_mod.get_frame(frame_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")


@app.get("/api/frames/{frame_id}/raw")
def api_get_frame_raw(frame_id: str) -> JSONResponse:
    """Return the frame's raw stored shape: unfiltered fields (all editable
    flags), stored ``drawlang`` (no ``_apply_values`` rewrite), and metadata.

    The Frame Editor uses this to load the true editable state; the plain
    ``GET /api/frames/{id}`` returns only editable fields with resolved
    ``value``s, which is the render-time shape (kept for backward compat).
    """
    with _frames_mod._lock:  # type: ignore[attr-defined]
        row = _frames_mod._conn().execute(  # type: ignore[attr-defined]
            "SELECT id, name, source, drawlang, fields_json, "
            "       created_at, updated_at "
            "FROM frames WHERE id = ?",
            (frame_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")
    d = _frames_mod._row_to_dict(row)  # type: ignore[attr-defined]
    return JSONResponse({
        "id": d["id"],
        "name": d["name"],
        "source": d["source"],
        "drawlang": d["drawlang"],
        "fields": d["fields"],  # raw list, all fields, with default/line_index/editable
    })


@app.get("/api/frames/{frame_id}/tokens")
def api_frame_tokens(frame_id: str) -> JSONResponse:
    """Return `{{name}}` tokens found in the frame's drawlang.

    Response:
      - `tokens`: distinct tokens in first-seen order.
      - `declared`: tokens already listed as fields.
      - `undeclared`: tokens in drawlang not yet declared as fields.

    The Fields tab uses `undeclared` to power its "scan drawlang for
    undeclared tokens" button.
    """
    try:
        frame = _frames_mod.get_frame(frame_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")
    prog = frame.get("drawlang") or ""
    tokens = _canvases.extract_tokens(prog)
    declared_names = {
        f["name"] for f in (frame.get("fields") or [])
        if isinstance(f, dict) and f.get("name")
    }
    declared = [t for t in tokens if t in declared_names]
    undeclared = [t for t in tokens if t not in declared_names]
    return JSONResponse({
        "frame_id": frame_id,
        "tokens": tokens,
        "declared": declared,
        "undeclared": undeclared,
    })


class FrameValues(BaseModel):
    values: dict[str, str]


@app.post("/api/frames/{frame_id}/render")
def api_render_frame(frame_id: str, req: FrameValues) -> JSONResponse:
    """
    Apply field values to the frame source and render.
    Returns {ok, output (SVG), fields}. Never mutates stored frame files.
    """
    try:
        composed = _frames_mod.get_frame(frame_id, values=req.values)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")

    try:
        svg = render(composed["drawlang"], backend="svg")
    except DrawLangError as e:
        return JSONResponse({
            "ok": False,
            "error": str(e),
            "error_kind": type(e).__name__,
            "statement_index": getattr(e, "statement_index", None),
        })
    return JSONResponse({
        "ok": True,
        "output": svg,
        "fields": composed["fields"],
        "drawlang": composed["drawlang"],
    })


class FrameCreateRequest(BaseModel):
    id: str
    name: str
    drawlang: str
    fields: list[dict] = []
    source: str = ""


class FramePatchRequest(BaseModel):
    name: str | None = None
    drawlang: str | None = None
    fields: list[dict] | None = None
    source: str | None = None


@app.post("/api/frames")
def api_frame_create(req: FrameCreateRequest) -> JSONResponse:
    """Create a new frame. Returns the created frame or 409 on id clash."""
    try:
        data = _frames_mod.create_frame(
            frame_id=req.id,
            name=req.name,
            drawlang=req.drawlang,
            fields=req.fields,
            source=req.source,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return JSONResponse({"ok": True, "frame": data})


@app.patch("/api/frames/{frame_id}")
def api_frame_update(frame_id: str, req: FramePatchRequest) -> JSONResponse:
    """Patch a frame's name/drawlang/fields/source."""
    try:
        data = _frames_mod.update_frame(
            frame_id,
            name=req.name,
            drawlang=req.drawlang,
            fields=req.fields,
            source=req.source,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")
    return JSONResponse({"ok": True, "frame": data})


@app.delete("/api/frames/{frame_id}")
def api_frame_delete(frame_id: str) -> JSONResponse:
    """Delete a frame. Canvases referencing it keep their frame_id."""
    ok = _frames_mod.delete_frame(frame_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"frame {frame_id!r} not found")
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Canvases API (Step 3: read-only; writes come in Step 4)
# ---------------------------------------------------------------------------

class CanvasCreateRequest(BaseModel):
    name: str
    frame_id: str | None = None
    program: str = ""
    slug: str | None = None
    field_values: dict | None = None  # v0.7.6


class CanvasPatchRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    frame_id: str | None = None
    field_values: dict | None = None  # v0.7.6


@app.get("/api/canvases")
def api_canvases_list() -> dict:
    """List all canvases with statement counts."""
    return {"canvases": _canvases.list_canvases()}


@app.post("/api/canvases")
def api_canvases_create(req: CanvasCreateRequest) -> dict:
    """
    Create a canvas. `frame_id` is stored as-is; the frame is composed at
    render time (see get_canvas_program). The canvas body starts empty
    unless the caller supplies `program`.
    """
    program = req.program or ""
    # If a frame is specified, verify it exists so we fail fast on bad ids.
    if req.frame_id:
        try:
            _frames_mod.get_frame(req.frame_id, values={})
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"frame {req.frame_id!r} not found"
            )
    try:
        data = _canvases.create_canvas(
            name=req.name,
            frame_id=req.frame_id,
            program=program,
            slug=req.slug,
            field_values=req.field_values,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, **data}


@app.get("/api/canvases/{id_or_slug}")
def api_canvases_get(id_or_slug: str) -> dict:
    """Return one canvas + all its statements in seq order."""
    data = _canvases.get_canvas(id_or_slug)
    if data is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return data


@app.get("/api/canvases/{id_or_slug}/program", response_class=Response)
def api_canvases_program(id_or_slug: str) -> Response:
    """Reconstruct the drawlang program by joining statements in order."""
    program = _canvases.get_canvas_program(id_or_slug)
    if program is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return Response(content=program, media_type="text/plain")


@app.post("/api/canvases/{id_or_slug}/render")
def api_canvases_render(id_or_slug: str, tagged: bool = False) -> dict:
    """Render a canvas by joining its statements and running the interpreter.

    When ``tagged=true``, each canvas statement's SVG output is wrapped in
    a ``<g data-statement-id="N">`` where N is the DB row id, so the
    editor can round-trip clicks between the rendered element and the
    statements list. Frame statements are unwrapped (they are not
    editable rows in the canvas). The language layer is unchanged; the
    wrapping happens in editor.app.tagged_svg.
    """
    data = _canvases.get_canvas(id_or_slug)
    if data is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    program = _canvases.get_canvas_program(id_or_slug)
    if program is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    try:
        if tagged:
            # Build source_index -> row_id map. Frame statements (if any)
            # come first in the composed program; they get consecutive
            # source_index values starting at 0. Canvas rows come after,
            # with source_index starting at the frame statement count.
            frame_len = _count_frame_statements(data)
            source_to_row = {
                frame_len + i: r["id"]
                for i, r in enumerate(data["statements"])
            }
            backend = _tagged.TaggedSVGBackend()
            backend.set_source_to_row_map(source_to_row)
            svg = _tagged.run_tagged(program, backend)
        else:
            svg = render(program, backend="svg")
    except DrawLangError as e:
        return {
            "ok": False,
            "error": str(e),
            "error_kind": type(e).__name__,
            "statement_index": getattr(e, "statement_index", None),
        }
    return {"ok": True, "output": svg}


def _count_frame_statements(canvas_data: dict) -> int:
    """Count how many statements the frame contributes to the composed program.

    The frame's drawlang is prepended before the canvas body, so its
    statements consume source_index positions 0..N-1 in the parsed
    program. We only need the count, not the parsed statements.
    """
    frame_id = canvas_data["canvas"].get("frame_id")
    if not frame_id:
        return 0
    try:
        from app import frames as _frames_mod  # local import to dodge cycles
        frame = _frames_mod.get_frame(frame_id)
        prog = (frame or {}).get("drawlang") or (frame or {}).get("program") or ""
        if not prog:
            return 0
        from drawlang.parser import parse as _parse
        return len(_parse(prog))
    except Exception:
        return 0


@app.delete("/api/canvases/{id_or_slug}")
def api_canvases_delete(id_or_slug: str) -> dict:
    """Delete a canvas + all its statements."""
    ok = _canvases.delete_canvas(id_or_slug)
    if not ok:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True}


@app.patch("/api/canvases/{id_or_slug}")
def api_canvases_patch(id_or_slug: str, req: CanvasPatchRequest) -> dict:
    """Rename a canvas, change its slug, change its frame, or update its
    frame field_values.

    Omitted fields are preserved. Only fields explicitly present in the
    request body are updated. To clear the frame, send frame_id as an
    empty string. field_values passes straight to the canvas row.
    """
    payload = req.dict(exclude_unset=True)
    try:
        data = _canvases.update_canvas(id_or_slug, **payload)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if data is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True, "canvas": data}


# ---------------------------------------------------------------------------
# Step 4: statement-write endpoints
# ---------------------------------------------------------------------------

class StatementItem(BaseModel):
    opcode: str
    args: str = ""
    group_id: str | None = None
    meaning_tag: str | None = None


class StatementAppendRequest(BaseModel):
    statements: list[StatementItem] | None = None
    program: str | None = None


class StatementPatchRequest(BaseModel):
    opcode: str | None = None
    args: str | None = None
    group_id: str | None = None
    meaning_tag: str | None = None


class ReorderRequest(BaseModel):
    order: list[int]


class CanvasDuplicateRequest(BaseModel):
    slug: str
    name: str | None = None


class StatementInsertRequest(BaseModel):
    seq: int
    opcode: str
    args: str = ""
    group_id: str | None = None
    meaning_tag: str | None = None


class ReplaceProgramRequest(BaseModel):
    program: str


@app.post("/api/canvases/{id_or_slug}/statements")
def api_statements_append(id_or_slug: str, req: StatementAppendRequest) -> dict:
    """Append statements (list) or raw program text to a canvas."""
    try:
        if req.program is not None:
            inserted = _canvases.append_program(id_or_slug, req.program)
        elif req.statements is not None:
            inserted = _canvases.append_statements(
                id_or_slug,
                [s.dict() for s in req.statements],
            )
        else:
            raise HTTPException(status_code=400, detail="statements or program required")
    except KeyError:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True, "inserted": inserted}


@app.patch("/api/canvases/{id_or_slug}/statements/{statement_id}")
def api_statement_patch(
    id_or_slug: str, statement_id: int, req: StatementPatchRequest
) -> dict:
    """Update one statement's opcode/args/group_id/meaning_tag.

    A field that is present in the JSON body but null clears the current
    value; a field that is missing preserves it. This matters most for
    `meaning_tag` — clients need a way to remove a tag.
    """
    # Pydantic v1: exclude_unset keeps the None-vs-missing distinction.
    patch = req.dict(exclude_unset=True)
    updated = _canvases.update_statement(id_or_slug, statement_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="canvas or statement not found")
    return {"ok": True, "statement": updated}


@app.delete("/api/canvases/{id_or_slug}/statements/{statement_id}")
def api_statement_delete(id_or_slug: str, statement_id: int) -> dict:
    ok = _canvases.delete_statement(id_or_slug, statement_id)
    if not ok:
        raise HTTPException(status_code=404, detail="canvas or statement not found")
    return {"ok": True}


@app.post("/api/canvases/{id_or_slug}/statements/reorder")
def api_statements_reorder(id_or_slug: str, req: ReorderRequest) -> dict:
    ok = _canvases.reorder_statements(id_or_slug, req.order)
    if not ok:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True}


@app.post("/api/canvases/{id_or_slug}/statements/insert")
def api_statement_insert(id_or_slug: str, req: StatementInsertRequest) -> dict:
    """v0.7 text-editor: insert a statement at an arbitrary seq position.

    Existing rows at or past ``seq`` are pushed down by one. Used by the
    statements panel to implement Enter-to-add-line-below and
    Cmd/Ctrl+Enter-to-add-line-above without falling back to reorder-then-append.
    """
    inserted = _canvases.insert_statement_at(
        id_or_slug,
        seq=req.seq,
        opcode=req.opcode,
        args=req.args,
        group_id=req.group_id,
        meaning_tag=req.meaning_tag,
    )
    if inserted is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True, "statement": inserted}


@app.put("/api/canvases/{id_or_slug}/program")
def api_replace_program(id_or_slug: str, req: ReplaceProgramRequest) -> dict:
    data = _canvases.replace_program(id_or_slug, req.program)
    if data is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"ok": True, **data}


# ---------------------------------------------------------------------------
# v0.7 undo/redo (per-canvas history stack)
# ---------------------------------------------------------------------------

@app.get("/api/canvases/{id_or_slug}/history")
def api_history(id_or_slug: str) -> dict:
    """Return {undo_depth, redo_depth} so the UI can enable/disable buttons."""
    try:
        return {"ok": True, **_canvases.history_depths(id_or_slug)}
    except KeyError:
        raise HTTPException(status_code=404, detail="canvas not found")


@app.post("/api/canvases/{id_or_slug}/undo")
def api_undo(id_or_slug: str) -> dict:
    data = _canvases.undo(id_or_slug)
    if data is None:
        # Distinguish empty stack (200 + no-op) from missing canvas (404).
        try:
            depths = _canvases.history_depths(id_or_slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="canvas not found")
        return {"ok": False, "reason": "undo stack empty", **depths}
    return {"ok": True, **data}


@app.post("/api/canvases/{id_or_slug}/duplicate")
def api_duplicate(id_or_slug: str, req: CanvasDuplicateRequest) -> dict:
    """v0.7 file management: deep-copy this canvas to a new slug."""
    try:
        data = _canvases.duplicate_canvas(id_or_slug, new_slug=req.slug, new_name=req.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="canvas not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "canvas": data.get("canvas", data)}


@app.post("/api/canvases/{id_or_slug}/redo")
def api_redo(id_or_slug: str) -> dict:
    data = _canvases.redo(id_or_slug)
    if data is None:
        try:
            depths = _canvases.history_depths(id_or_slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="canvas not found")
        return {"ok": False, "reason": "redo stack empty", **depths}
    return {"ok": True, **data}


# ---------------------------------------------------------------------------
# Step 10: semantic layer (meaning tags)
# ---------------------------------------------------------------------------


@app.get("/api/canvases/{id_or_slug}/meaning-index")
def api_meaning_index(id_or_slug: str) -> dict:
    """List distinct meaning tags on a canvas with statement counts."""
    if _canvases.get_canvas(id_or_slug) is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"index": _canvases.list_meaning_index(id_or_slug)}


@app.get("/api/canvases/{id_or_slug}/meaning/{meaning_tag:path}")
def api_meaning_get(id_or_slug: str, meaning_tag: str) -> dict:
    """Return every statement on a canvas that carries the given meaning tag.

    The `:path` converter lets meaning tags contain slashes, so hierarchical
    tags like `motor/pump-101/status` are addressable directly by URL.
    """
    if _canvases.get_canvas(id_or_slug) is None:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {
        "meaning_tag": meaning_tag,
        "statements": _canvases.list_statements_by_meaning(id_or_slug, meaning_tag),
    }


# ---------------------------------------------------------------------------
# Step 5: Library CRUD API + Step 8: drop-on-canvas
# ---------------------------------------------------------------------------


class LibraryCreateRequest(BaseModel):
    name: str
    program: str
    category: str = "symbol"
    description: str = ""
    anchor_x: float = 0.0
    anchor_y: float = 0.0
    slug: str | None = None


class LibraryPatchRequest(BaseModel):
    name: str | None = None
    program: str | None = None
    category: str | None = None
    description: str | None = None
    anchor_x: float | None = None
    anchor_y: float | None = None


class LibraryDropRequest(BaseModel):
    x: float
    y: float
    group_id: str | None = None


@app.get("/api/library")
def api_library_list(category: str | None = None) -> dict:
    return {"items": _library.list_items(category=category)}


@app.post("/api/library")
def api_library_create(req: LibraryCreateRequest) -> dict:
    try:
        item = _library.create_item(
            name=req.name, program=req.program, category=req.category,
            description=req.description, anchor_x=req.anchor_x,
            anchor_y=req.anchor_y, slug=req.slug,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "item": item}


@app.get("/api/library/{id_or_slug}")
def api_library_get(id_or_slug: str) -> dict:
    item = _library.get_item(id_or_slug)
    if item is None:
        raise HTTPException(status_code=404, detail="library item not found")
    return item


@app.patch("/api/library/{id_or_slug}")
def api_library_patch(id_or_slug: str, req: LibraryPatchRequest) -> dict:
    item = _library.update_item(id_or_slug, req.dict())
    if item is None:
        raise HTTPException(status_code=404, detail="library item not found")
    return {"ok": True, "item": item}


@app.delete("/api/library/{id_or_slug}")
def api_library_delete(id_or_slug: str) -> dict:
    ok = _library.delete_item(id_or_slug)
    if not ok:
        raise HTTPException(status_code=404, detail="library item not found")
    return {"ok": True}


@app.post("/api/library/{id_or_slug}/drop/{canvas_slug}")
def api_library_drop(
    id_or_slug: str, canvas_slug: str, req: LibraryDropRequest
) -> dict:
    """Drop a library item onto a canvas at (x,y). Appends statements."""
    try:
        inserted = _library.drop_on_canvas(
            id_or_slug, canvas_slug, req.x, req.y, group_id=req.group_id
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "inserted": inserted}


# ---------------------------------------------------------------------------
# Step 9: Voice / natural-language input
# ---------------------------------------------------------------------------

from app import nlp as _nlp  # noqa: E402


class NLPRequest(BaseModel):
    text: str
    canvas_id: str | None = None  # if set, statements are appended there


@app.post("/api/nlp/translate")
def api_nlp_translate(req: NLPRequest) -> dict:
    """Translate natural-language text into drawlang statements.

    If `canvas_id` is supplied, the translated statements are appended
    to that canvas and the inserted rows are returned. Otherwise the
    translated text is returned without side effects.
    """
    try:
        stmts = _nlp.translate_command(req.text)
    except _nlp.NLPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    program = "\n".join(stmts)
    if req.canvas_id:
        try:
            inserted = _canvases.append_program(req.canvas_id, program)
        except KeyError:
            raise HTTPException(status_code=404, detail="canvas not found")
        return {"ok": True, "program": program, "inserted": inserted}
    return {"ok": True, "program": program, "statements": stmts}


# ---------------------------------------------------------------------------
# Primitives catalog
# ---------------------------------------------------------------------------

from app import primitives as _primitives  # noqa: E402


class PrimitiveExpandRequest(BaseModel):
    values: dict = {}


@app.get("/api/primitives")
def api_primitives_list() -> dict:
    """List all primitives (light payload — no template)."""
    return {"ok": True, "primitives": _primitives.list_primitives()}


@app.get("/api/primitives/{prim_id}")
def api_primitives_get(prim_id: str) -> dict:
    """Return one primitive's full definition (incl. template)."""
    p = _primitives.get_primitive(prim_id)
    if p is None:
        raise HTTPException(status_code=404, detail="primitive not found")
    return {"ok": True, "primitive": p}


@app.post("/api/primitives/{prim_id}/expand")
def api_primitives_expand(prim_id: str, req: PrimitiveExpandRequest) -> dict:
    """Expand a primitive with user-supplied params into drawlang.

    Returns ``{drawlang, meaning_tag}``. The client typically POSTs
    ``drawlang`` into ``/api/canvases/{slug}/statements`` with
    ``meaning_tag`` attached to the first inserted statement.
    """
    p = _primitives.get_primitive(prim_id)
    if p is None:
        raise HTTPException(status_code=404, detail="primitive not found")
    try:
        drawlang, tag = _primitives.expand(p, req.values or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "drawlang": drawlang, "meaning_tag": tag}


# ---------------------------------------------------------------------------
# Opcode catalog (v0.7 editor Primitives tab)
#
# One editable row per v0.6 opcode. This is the FULL Primitives set:
# nothing composed, nothing invented. See editor/app/opcodes.py.
# ---------------------------------------------------------------------------

from app import opcodes as _opcodes  # noqa: E402


@app.get("/api/opcodes")
def api_opcodes_list() -> dict:
    """Return the v0.6 opcode catalog for the Primitives tab.

    Response: {opcodes: [{opcode, name, group, description, spec_section, args:[...]}, ...]}
    """
    return {"ok": True, "opcodes": _opcodes.list_opcodes()}


@app.get("/api/opcodes/{opcode}")
def api_opcodes_get(opcode: str) -> dict:
    op = _opcodes.get_opcode(opcode)
    if op is None:
        raise HTTPException(status_code=404, detail="opcode not found")
    return {"ok": True, "opcode": op}
