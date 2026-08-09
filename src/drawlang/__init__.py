"""
drawlang — Reference interpreter for the Drawing Language v0.5.

Implements the language defined in ../../spec/DRAWING-LANGUAGE-SPEC.md exactly.

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

__version__ = "0.5.0"
SPEC_VERSION = "0.5"
# v0.3: FLOAT type removed. All numeric args are INT (signed 16-bit).
# v0.4: `dl` accepts the `i` (invisible) modifier, matching `rt` and `ci`.
#        An invisible line advances the pen and contributes both endpoints to
#        the bounding box but emits no visible mark.
# v0.5: `ci` and `rt` accept the `t` modifier, observed in real ES680 pic_ex
#        symbols (~77 occurrences in the shipped library). Semantics are
#        currently reserved: parsers MUST accept `,t` on ci and rt; interpreters
#        MUST NOT reject; the reference backend renders the shape identically
#        to the same statement without `,t`. A future spec revision may attach
#        visible semantics to `,t` once the ES680 source documentation is
#        cross-referenced. See spec §8.1 and §14.
# Literals with a decimal point are accepted and rounded half-toward-positive-
# infinity to the nearest int. See spec §3.4.


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
