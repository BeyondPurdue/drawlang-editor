# Contributing to drawlang / Beyond Purdue Editor

Thanks for considering a contribution. This project is small, opinionated, and moves in deliberate steps. Read this document before opening a large PR.

## Ground rules

1. **The language spec is LOCKED at v0.1.** No opcode additions, argument changes, or modifier changes happen without a formal v0.2 event with community review on [r/BeyondPurdue](https://www.reddit.com/r/BeyondPurdue/). Interpreter, backend, and editor changes are always welcome.
2. **Strict separation of concerns.** The interpreter never imports a backend. Backends never import each other. The editor depends on `drawlang` only through its public API. PRs that cross these boundaries will be asked to refactor.
3. **Determinism.** Given the same program and starting pen state, output must be byte-identical across runs. No randomness, no wall-clock reads, no floating-point tolerance leaking into the language surface.
4. **Small PRs.** One concern per PR. Rebase, don't merge.

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

## What we welcome

- **Backends.** New output targets (Canvas, DXF, HPGL, Tikz…). Implement the `drawlang.backend.Backend` protocol; add a module under `src/drawlang/backends/`; add tests.
- **Editor features.** Better palette browsing, keyboard shortcuts, template categories, drawing-to-database export.
- **Documentation.** Tutorials, worked examples, screencasts, translations of the spec's introduction (spec body stays in English).
- **Starter templates.** Add public-domain drawings to `editor/library-data/` with a note on provenance.
- **Bug fixes.** Especially interpreter fidelity vs. spec §9.

## What we don't merge

- New syntactic forms in the language (blocks, variables, conditionals, macros) — the language is deliberately flat.
- Backend-specific escape hatches in programs (e.g. `svg-raw` opcode).
- Silent tolerance / rounding that hides interpreter bugs.
- Non-deterministic behavior.

## Reporting bugs

Open a [GitHub issue](https://github.com/BeyondPurdue/drawlang-editor/issues) with:

- The exact program text.
- The backend and version.
- What you expected vs. what you got (attach the rendered file if visual).
- Your Python version and OS.

## Pull request checklist

- [ ] Tests pass (`pytest`).
- [ ] New code is covered by a test.
- [ ] No new dependency added without a note in the PR description.
- [ ] Docstrings and README updated if user-facing behavior changed.
- [ ] No references to obsolete internal names (see the glossary in the spec for canonical terms).

## Commit messages

Use short imperative subjects:

```
add DXF backend skeleton
fix ar opcode negative-radius handling
docs: clarify pen state after tz
```

## Licensing

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE) and can be redistributed as part of this project. Contributors retain copyright on their contributions; the collective work is © Beyond Purdue contributors.

## Code of conduct

All participation is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Be kind.
