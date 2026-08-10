# Documentation

Human-facing documentation for the DrawLang language and Beyond Purdue editor.

Code lives at the repo root (`editor/`, `src/`, `tests/`, `deploy/`); this folder holds only prose, specs, and diagrams.

## Layout

```
docs/
├── spec/           DrawLang specification (current + history) + coordinate system note
├── editor/         Editor v2 architecture and REST API
├── diagrams/       SVG diagrams referenced from the docs
└── deploy/         Runbooks for deploying the editor
```

## Where to start

1. **[`spec/drawing-language-spec.md`](spec/drawing-language-spec.md)** — the current, locked v0.6 language specification. Grammar, opcodes, worked examples.
2. **[`editor/v2-architecture.md`](editor/v2-architecture.md)** — the editor architecture and REST API design.

## What's in each folder

### `spec/` — Specifications

| File | Purpose |
|---|---|
| [`spec/drawing-language-spec.md`](spec/drawing-language-spec.md) | DrawLang v0.6 — the current, frozen specification. Grammar, opcodes, modifiers, palette, examples. |
| [`spec/drawing-language-spec.docx`](spec/drawing-language-spec.docx) | Same, rendered to Word. |
| [`spec/coordinate-system-and-frames.md`](spec/coordinate-system-and-frames.md) | Coordinate system, frame geometry, A3/A4 layout math used by the editor. |
| [`spec/history/`](spec/history/) | Frozen v0.1 → v0.6 snapshots. |

### `editor/` — Editor v2 design

| File | Purpose |
|---|---|
| [`editor/v2-architecture.md`](editor/v2-architecture.md) | Editor architecture, data model, REST API, component tree, UI wireframes. |

### `diagrams/` — SVG diagrams

| File | Purpose |
|---|---|
| [`diagrams/render-pipeline.svg`](diagrams/render-pipeline.svg) | Rendering pipeline: DB → DrawLang program → PageDescription → PS/PDF/SVG. |
| [`diagrams/data-model-er.svg`](diagrams/data-model-er.svg) | Editor data model (drawings, symbols, frames, placements). |
| [`diagrams/editor-component-tree.svg`](diagrams/editor-component-tree.svg) | Editor React component tree. |

### `deploy/`

| File | Purpose |
|---|---|
| [`deploy/bootstrap.md`](deploy/bootstrap.md) | Hetzner CX22 bootstrap runbook for deploying the editor. |

Deploy scripts and systemd units themselves live at the repo root under `deploy/`.

## Contributing

- Markdown is the source of truth for every document. Word (`.docx`) files, when present, are generated from the Markdown via `pandoc` and should not be edited directly.
- German technical vocabulary (Pictogramm, Baustein, Konnektor, Rahmen, Raster, Maske) is preserved where it improves clarity.
