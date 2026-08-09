"""
drawlang — Reference interpreter for the Drawing Language v0.1.

Implements the language defined in ../../spec/DRAWLANG-SPEC-v0.1.md exactly.

Package layout — strict separation of concerns:

    drawlang/
        parser.py              — tokenizer + statement splitter + argument/modifier validator
        interpreter.py         — reference algorithm from spec §9, backend-neutral
        backend.py             — abstract backend interface every output format must implement
        errors.py              — LexicalError, SemanticError
        backends/
            svg.py             — cmd → SVG string
            ps.py              — cmd → PostScript string
            pdf.py             — cmd → PostScript → PDF (thin wrapper over ps.py + ps2pdf)

The interpreter itself never imports a concrete backend. `render()` here is a
convenience entry point that wires them together; callers who want strict
separation can call `interpret(program, backend)` with their own backend instance.

Public entry point:

    from drawlang import render
    render(program_text, backend="svg")   -> SVG string
    render(program_text, backend="ps")    -> PostScript string
    render(program_text, backend="pdf")   -> PDF bytes
"""

from .errors import DrawLangError, LexicalError, SemanticError
from .parser import parse, Statement
from .interpreter import interpret, PenState
from .backend import Backend

__version__ = "0.1.0"
SPEC_VERSION = "0.1"


def render(program_text: str, backend: str = "svg", **backend_options):
    """
    Convenience entry point: parse a program and render it with the named backend.

    backend: "svg" | "ps" | "pdf"
    backend_options: passed to the backend constructor (width, height, unit, etc.)
    """
    if backend == "svg":
        from .backends.svg import SVGBackend
        be = SVGBackend(**backend_options)
        interpret(program_text, be)
        return be.finalize()
    elif backend == "ps":
        from .backends.ps import PostScriptBackend
        be = PostScriptBackend(**backend_options)
        interpret(program_text, be)
        return be.finalize()
    elif backend == "pdf":
        from .backends.pdf import render_pdf
        return render_pdf(program_text, **backend_options)
    else:
        raise ValueError(f"unknown backend: {backend!r}. Use 'svg', 'ps', or 'pdf'.")


__all__ = [
    "render",
    "parse",
    "interpret",
    "Statement",
    "PenState",
    "Backend",
    "DrawLangError",
    "LexicalError",
    "SemanticError",
    "SPEC_VERSION",
]
