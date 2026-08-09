"""
Output backends for the drawlang interpreter.

Each backend is an independent module that implements the Backend interface
(drawlang.backend.Backend). The interpreter never imports these directly —
callers wire them together explicitly or through the drawlang.render()
convenience entry point.

Available backends:
    - drawlang.backends.svg   : cmd → SVG string
    - drawlang.backends.ps    : cmd → PostScript string
    - drawlang.backends.pdf   : cmd → PostScript → PDF (via ps2pdf)
"""
