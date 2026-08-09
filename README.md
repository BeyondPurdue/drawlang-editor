# drawlang — Beyond Purdue Editor

A tiny, deterministic drawing language and its reference interpreter and web editor.

**Every visible mark on a drawing — every line, arc, symbol, character of text — is a database record.**
Nothing is drawn by ad-hoc code. Programs in the language are short ASCII strings executed by a pen-state
interpreter. Backends translate the interpreter's abstract calls into SVG, PostScript, or PDF.

- **Language spec:** [`spec/DRAWLANG-SPEC-v0.1.md`](spec/DRAWLANG-SPEC-v0.1.md) — LOCKED at v0.1.
- **Community:** [r/BeyondPurdue](https://www.reddit.com/r/BeyondPurdue/)
- **License:** Apache 2.0 — © 2026 Beyond Purdue contributors

---

## Why

CAD and diagram tools bake geometry into code. That makes drawings unreproducible: change the tool, lose the drawings. This project inverts the model:

1. The **language** defines all drawing primitives — 7 core opcodes + 4 extensions. Frozen at v0.1.
2. The **interpreter** is a pure pen-state machine — no output-format knowledge.
3. **Backends** (SVG / PostScript / PDF) are independent modules that receive abstract drawing calls.
4. The **editor** is a thin web UI over interpreter + backends. Programs are stored as text; renders are disposable.

Any drawing you make is a plain text program you can commit to git, diff, template, and round-trip through any compliant interpreter forever.

---

## Architecture — strict separation of concerns

```
┌─────────────────────────────────────────────────────────────┐
│  spec/                                                      │
│  DRAWLANG-SPEC-v0.1.md — the language, code-free, locked    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  src/drawlang/                                              │
│    parser.py       — tokenize + validate                    │
│    interpreter.py  — pen-state machine (spec §9)            │
│    backend.py      — abstract Backend interface             │
│    errors.py       — LexicalError, SemanticError            │
│    backends/                                                │
│      svg.py        — → SVG                                  │
│      ps.py         — → PostScript                           │
│      pdf.py        — → PDF (ps.py + ps2pdf)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  editor/                                                    │
│    app/main.py     — FastAPI backend                        │
│    static/         — single-page textarea + live SVG        │
│    library-data/   — starter template library               │
│    user_drawings/  — drawings you save (git-friendly text)  │
└─────────────────────────────────────────────────────────────┘
```

**The interpreter never imports a backend.** Backends never import the interpreter.
`drawlang.render(program, backend="svg" | "ps" | "pdf")` is a convenience wrapper that wires them.

---

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/BeyondPurdue/drawlang-editor.git
cd drawlang-editor

# core interpreter only
pip install -e .

# core + web editor
pip install -e ".[editor]"
```

PDF backend additionally requires **ghostscript** (`ps2pdf`) in `PATH`.

---

## Quickstart

### As a library

```python
from drawlang import render

program = """
mr,0,158;
dl,14,0;
mr,0,-1;
dl,-14,0;
tz,8;
tx,0.,A1;
"""

svg = render(program, backend="svg")
ps  = render(program, backend="ps")
pdf = render(program, backend="pdf")   # bytes
```

### The web editor

```bash
uvicorn editor.app.main:app --port 8000
```

Open <http://localhost:8000>. Type a program on the left, see live SVG on the right, export PS or PDF, save to `user_drawings/`.

---

## The language in 60 seconds

Seven core opcodes, four extensions. Two-letter mnemonics, comma-separated args, semicolon-terminated.

| Opcode | Meaning                    |
| ------ | -------------------------- |
| `mr`   | move relative              |
| `ma`   | move absolute              |
| `dl`   | draw line (relative)       |
| `rt`   | rectangle                  |
| `ci`   | circle                     |
| `tz`   | text size                  |
| `tx`   | text                       |
| `ar`   | arc (extension)            |
| `bz`   | Bézier curve (extension)   |
| `sp`   | spline (extension)         |
| `im`   | image reference (extension)|

Modifiers `,f` (fill), `,i` (invisible), `,d` (dashed), `,c`*n* (color) tweak individual statements.

See the [language specification](spec/DRAWLANG-SPEC-v0.1.md) for the full grammar, semantics, worked examples, and the reference algorithm.

---

## Storage model

Drawings are database records. Each table row holds one cmd string:

| Table         | Purpose                                              |
| ------------- | ---------------------------------------------------- |
| `symbol`      | Reusable graphical block                             |
| `extsym`      | Multi-segment symbol (also used for frame guides)    |
| `instance`    | A placement of a symbol on a drawing                 |
| `connector`   | A wire between two instances                         |
| `label`       | A free-standing text label                           |
| `frame`       | Sheet border + drawing area                          |
| `titleblock`  | Field data for a frame's title block                 |

The schema for these tables is out of scope for the language spec — the language only cares about the cmd strings.

---

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Conformance tests live in `tests/test_conformance.py` and cover every core opcode against the reference algorithm in spec §9.

---

## Contributing

Contributions welcome — bug reports, new backends, editor features, documentation, additional starter templates.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.
- Read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- The language spec is LOCKED at v0.1. Extensions must go through a formal v0.2 event with community review.

---

## Community

- **Reddit:** [r/BeyondPurdue](https://www.reddit.com/r/BeyondPurdue/) — discussions, drawings, questions
- **Issues:** [GitHub issues](https://github.com/BeyondPurdue/drawlang-editor/issues) — bugs and feature requests

---

## License

Apache License 2.0. Copyright © 2026 Beyond Purdue contributors. See [LICENSE](LICENSE).
