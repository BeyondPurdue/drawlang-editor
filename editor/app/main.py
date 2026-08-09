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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the sibling `interpreter` package importable regardless of cwd
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "interpreter"))

from drawlang import SPEC_VERSION, render  # noqa: E402
from drawlang.errors import DrawLangError  # noqa: E402

from app.import_library import load_templates, build_catalog  # noqa: E402


app = FastAPI(title="Drawing Language Editor", version=SPEC_VERSION)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


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


@app.post("/export/pdf")
def export_pdf(req: RenderRequest) -> Response:
    """Render the program to PostScript, then convert to PDF via ps2pdf."""
    try:
        ps = render(req.program, "ps")
    except DrawLangError as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")

    with tempfile.TemporaryDirectory() as td:
        ps_path = Path(td) / "drawing.ps"
        pdf_path = Path(td) / "drawing.pdf"
        ps_path.write_text(ps, encoding="ascii")
        result = subprocess.run(
            ["ps2pdf", str(ps_path), str(pdf_path)],
            capture_output=True, text=True,
        )
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


USER_DRAWINGS_DIR = Path(__file__).resolve().parent.parent / "user_drawings"
USER_DRAWINGS_DIR.mkdir(exist_ok=True)


class SaveRequest(BaseModel):
    name: str
    program: str
    source_id: str | None = None  # e.g. 'frame-1' or 'picb-3204' if forked


@app.post("/save")
def save_drawing(req: SaveRequest) -> JSONResponse:
    """
    Persist an edited program as a .cmd file under user_drawings/.

    Name is slugified for the filename. The saved file is a plain
    drawlang program with a small header comment recording the source
    template (if any). This is the user's own drawing and belongs to
    them — the library templates remain read-only.
    """
    import re
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", req.name.strip()) or "drawing"
    if not slug.endswith(".cmd"):
        slug += ".cmd"
    path = USER_DRAWINGS_DIR / slug
    header = ["# User drawing (Beyond Purdue Editor)"]
    if req.source_id:
        header.append(f"# Forked from: {req.source_id}")
    header.append(f"# Saved as: {slug}")
    header.append("")
    path.write_text("\n".join(header) + req.program, encoding="utf-8")
    return JSONResponse({"ok": True, "path": str(path.name), "slug": slug})


@app.get("/drawings")
def list_drawings() -> JSONResponse:
    """List all saved user drawings."""
    items = []
    for p in sorted(USER_DRAWINGS_DIR.glob("*.cmd")):
        items.append({
            "id": f"user-{p.stem}",
            "title": p.stem,
            "category": "My drawings",
            "program": p.read_text(encoding="utf-8"),
            "description": f"User drawing saved as {p.name}.",
        })
    return JSONResponse(items)


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


def _load_library_templates() -> list[dict]:
    """Load templates from ../library-data/*.csn."""
    data_dir = Path(__file__).resolve().parent.parent / "library-data"
    if not data_dir.exists():
        return []
    try:
        data = load_templates(data_dir)
        catalog = build_catalog(data)
        # Add a description for each
        for entry in catalog:
            entry["description"] = f"Imported from library ({entry['source']['table']})."
        return catalog
    except Exception:
        # Never let a bad backup take the editor down
        return []


_LIBRARY_TEMPLATES = _load_library_templates()
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
