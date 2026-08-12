# Contributing to drawlang / Beyond Purdue Editor

Thanks for considering a contribution. This project is small, opinionated, and moves in deliberate steps. Read this document before opening a PR.

## Ground rules

1. **The language spec is LOCKED at v0.6.** No opcode additions, argument changes, or modifier changes happen without a formal v0.7 event with community review on [r/drawlang](https://www.reddit.com/r/drawlang/). Interpreter, backend, editor, and frame changes are always welcome inside the frozen grammar.
2. **API is the only path.** Every mark on every canvas is produced by posting drawlang statements to the editor's `POST /api/canvases/{id}/statements` endpoint. The graphical editor, the CLI tools, and the voice/AI input all use exactly this endpoint. No side channels, no client-only geometry, no hidden primitives. This rule applies to contributions too — features that bypass the API will be asked to refactor.
3. **KISS.** Anything more complex than the simplest working answer needs justification. If a feature can't be expressed in v0.6, open a discussion issue first — don't work around it in the editor.
4. **Strict separation of concerns.** The interpreter never imports a backend. Backends never import each other. The editor depends on `drawlang` only through its public API. Groups (see below) live inside drawlang source as comment fences, not as a runtime type. PRs that cross these boundaries will be asked to refactor.
5. **Determinism.** Given the same program and starting pen state, output must be byte-identical across runs. No randomness, no wall-clock reads, no floating-point tolerance leaking into the language surface.
6. **No vendor names in the public repo.** This repo is a clean-room implementation of a drawing language. Do not reintroduce vendor product or company names in comments, code, documentation, tests, frames, or examples. Descriptive terms like "legacy HMI" or "legacy backup archive" are fine when historical context is genuinely needed.
7. **Small PRs.** One concern per PR. Rebase, don't merge.

## Development setup

```bash
git clone https://github.com/BeyondPurdue/drawlang-editor.git
cd drawlang-editor
python -m venv .venv
source .venv/bin/activate
pip install -e ".[editor,dev]"
pytest
```

Run the editor locally:

```bash
uvicorn editor.app.main:app --reload --port 8000
```

Then open `http://localhost:8000/` for the main editor and `http://localhost:8000/frames-editor` for the frame preview.

## Grid convention

Frames in this project use an **A3 landscape 28-column x 14-row grid** with perfect-square cells (cell edge = 1080/28 = 38.5714 drawlang units). Column numbers 1..28 run left to right; row letters A..N run top to bottom on both edges. Coordinate origin is bottom-left, y-up, matching drawlang v0.6.

When you contribute a new frame, place it in `frames/<name>.drawlang` with an optional `frames/<name>.fields.json` for editable-field metadata. Frames are auto-discovered at startup.

## Groups

A **Group** is a named block of drawlang statements delimited by two comment lines:

```
# group name=motor id=M#1 origin=200,300
mr,0,20;
dl,40,0;
...
# end group id=M#1
```

The renderer ignores group fences (they are comments in v0.6). The editor treats the block as one selectable unit. **No new opcode.** If you want to add a group-like feature, do it inside this fence convention.

## What we welcome

- **Backends.** New output targets (Canvas, DXF, HPGL, TikZ, PDF variants). Implement the `drawlang.backend.Backend` protocol; add a module under `src/drawlang/backends/`; add tests.
- **Editor features.** Better palette browsing, keyboard shortcuts, group management UX, library thumbnails, voice-command coverage.
- **Documentation.** Tutorials, worked examples, screencasts, translations of the spec's introduction (spec body stays in English).
- **Starter templates and frames.** A3 grid frames for other paper sizes (A2, A4, US Letter). Add them to `frames/` with a matching `.fields.json` and a note on provenance in the PR description.
- **Bug fixes.** Especially interpreter fidelity vs. spec section 9 and frame render regressions.

## What we don't merge

- New syntactic forms in the language (blocks, variables, conditionals, macros, subroutines) — the language is deliberately flat.
- Backend-specific escape hatches in programs (e.g. `svg-raw` opcode).
- Silent tolerance / rounding that hides interpreter bugs.
- Non-deterministic behavior.
- Vendor names or product references (see rule 6).
- Client-side geometry that bypasses the statements API.

## Reporting bugs

Open a [GitHub issue](https://github.com/BeyondPurdue/drawlang-editor/issues) with:

- The exact program text (or the `POST /api/canvases/{id}/statements` payload).
- The backend and version.
- What you expected vs. what you got (attach the rendered file if visual).
- Your Python version and OS.

## Pull request checklist

- [ ] Tests pass (`pytest`).
- [ ] New code is covered by a test.
- [ ] No new dependency added without a note in the PR description.
- [ ] Docstrings and README updated if user-facing behavior changed.
- [ ] No vendor names introduced anywhere (see rule 6).
- [ ] No references to obsolete internal names (see the glossary in the spec for canonical terms).
- [ ] If the change touches a frame, a rendered PNG at 1600px width is attached to the PR.

## Commit messages

Use short imperative subjects:

```
add DXF backend skeleton
fix ar opcode negative-radius handling
docs: clarify pen state after tz
frames: add A2 landscape 28x14 grid
```

## Licensing

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE) and can be redistributed as part of this project. Contributors retain copyright on their contributions; the collective work is (c) Beyond Purdue contributors.

## Code of conduct

All participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Be kind.
