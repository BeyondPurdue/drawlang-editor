"""
PDF backend — thin wrapper that renders to PostScript and converts to PDF via ps2pdf.

This backend does NOT know about the drawing language directly. It reuses the
PostScript backend and shells out to ps2pdf. Requires ghostscript / ps2pdf
in PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..interpreter import interpret
from .ps import PostScriptBackend


def render_pdf(program_text: str, **ps_options) -> bytes:
    """
    Render a drawlang program to PDF bytes.

    Pipeline:
        program_text
          → interpret + PostScriptBackend  → PostScript string
          → ps2pdf                         → PDF bytes
    """
    if shutil.which("ps2pdf") is None:
        raise RuntimeError(
            "ps2pdf not found in PATH. Install ghostscript (which provides ps2pdf) "
            "to enable the PDF backend."
        )

    be = PostScriptBackend(**ps_options)
    interpret(program_text, be)
    ps_text = be.finalize()

    with tempfile.TemporaryDirectory() as td:
        ps_path = Path(td) / "drawing.ps"
        pdf_path = Path(td) / "drawing.pdf"
        ps_path.write_text(ps_text, encoding="utf-8")
        proc = subprocess.run(
            ["ps2pdf", str(ps_path), str(pdf_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ps2pdf failed: {proc.stderr}")
        return pdf_path.read_bytes()


__all__ = ["render_pdf"]
