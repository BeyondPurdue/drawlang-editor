# Documentation

Human-facing documentation for the ES680 Drawing System reverse-engineering and replica-editor project.

Code lives at the repo root (`editor/`, `research/`, `src/`, `tests/`, `data/`, `deploy/`); this folder holds only prose, specs, and study reports.

## Layout

```
docs/
├── spec/           Consolidated reference + drawing-language spec (current + history)
├── editor/         Editor v2 architecture, API, wireframes
├── diagrams/       SVG diagrams referenced from the docs
├── studies/        Reconstruction studies against real project dumps
├── notes/          Working notes on the ES680 data model and rendering
├── inventory/      Google Drive inventory of ES680 backups and printouts
├── examples/       Rendered artifacts referenced from the docs
└── deploy/         Runbooks for deploying the editor
```

## Where to start

1. **[`spec/es680-drawing-system-consolidated.md`](spec/es680-drawing-system-consolidated.md)** — the single "everything we know" reference. If you read one document, read this one.
2. **[`editor/v2-architecture.md`](editor/v2-architecture.md)** — the editor we're designing. Awaiting review before any code is written.

## What's in each folder

### `spec/` — Specifications

The consolidated reference plus the mini-language ("pen instructions") specification.

| File | Purpose |
|---|---|
| [`spec/es680-drawing-system-consolidated.md`](spec/es680-drawing-system-consolidated.md) | **Everything we know** — data model, mini-language, coordinate system, rendering pipeline, reconstruction proof, open items |
| [`spec/drawing-language-spec.md`](spec/drawing-language-spec.md) | Formal `cmd` specification (grammar + worked examples) |
| [`spec/drawing-language-spec.docx`](spec/drawing-language-spec.docx) | Same, rendered to Word |
| [`spec/history/`](spec/history/) | Frozen v0.1 → v0.6 snapshots |

### `editor/` — Editor v2 design

| File | Purpose |
|---|---|
| [`editor/v2-architecture.md`](editor/v2-architecture.md) | Editor rewrite: architecture, data model, REST API, component tree, UI wireframes. **Awaiting review — no code yet.** |

### `diagrams/` — SVG diagrams

| File | Purpose |
|---|---|
| [`diagrams/render-pipeline.svg`](diagrams/render-pipeline.svg) | ES680 rendering pipeline (DB → PageDescription → PS/PDF/SVG) |
| [`diagrams/data-model-er.svg`](diagrams/data-model-er.svg) | ES680 data-model families (catalog + user + cross-refs) |
| [`diagrams/editor-component-tree.svg`](diagrams/editor-component-tree.svg) | Editor v2 React component tree |
| [`diagrams/editor-wireframe.svg`](diagrams/editor-wireframe.svg) | Editor v2 main-screen wireframe |

### `studies/` — Reconstruction studies

End-to-end verifications that the ES680 Ingres backups contain everything needed to reconstruct real project printouts.

| File | Purpose |
|---|---|
| [`studies/sagunto-u10-db-to-printout.md`](studies/sagunto-u10-db-to-printout.md) | Sagunto Unit 10 DB-to-printout study. §1–11: three-plan proof (YDH / YDM / YDR). §12: 010a-dump reconstruction check across 10 randomly picked plans (8 YFR / 1 YDR / 1 YDM). |
| [`studies/sagunto-u10-db-to-printout.docx`](studies/sagunto-u10-db-to-printout.docx) | Same, rendered to Word |

### `notes/` — ES680 data-model working notes

Numbered, ordered notes explaining what each part of the ES680 system does.

| File | Topic |
|---|---|
| [`notes/00-index.md`](notes/00-index.md) | Overall index of the notes |
| [`notes/01-overview.md`](notes/01-overview.md) | System overview |
| [`notes/02-drawing-engine.md`](notes/02-drawing-engine.md) | Drawing engine core (`pic_b`, `pic_ex`, `pic_d`, `frame`, `raster`, `msk_g`, `msk_b`) |
| [`notes/03-user-project-tables.md`](notes/03-user-project-tables.md) | User project tables (`obj_f`, `obj_g`, `obj_d`, `obj_s`, `ver_b`, `konnektor`, `schr_d`) |
| [`notes/04-system-stdplans-s5.md`](notes/04-system-stdplans-s5.md) | System std-plans and S5 APs |
| [`notes/05-cmd-mini-language.md`](notes/05-cmd-mini-language.md) | The `cmd` (vch256) mini-language used in `pic_ex.cmd` / `pic_b.cmd` |
| [`notes/06-render-architecture.md`](notes/06-render-architecture.md) | SVG renderer + web editor architecture |
| [`notes/07-coordinate-system-and-frames.md`](notes/07-coordinate-system-and-frames.md) | ES680 coordinate system and frame geometry |
| [`notes/es680-tables-real.md`](notes/es680-tables-real.md) | Notes on the real captured `.csn` tables |

### `inventory/` — Drive inventory

| File | Purpose |
|---|---|
| [`inventory/drive-inventory.md`](inventory/drive-inventory.md) | Full inventory of ES680 backups and printouts on Google Drive |
| [`inventory/backups-README.md`](inventory/backups-README.md) | Notes on the backups collection |

### `examples/`

| File | Purpose |
|---|---|
| [`examples/phase1-a3-frame.pdf`](examples/phase1-a3-frame.pdf) | Phase 1 A3 FUP frame (BM Global) |
| [`examples/pictogram-gallery.html`](examples/pictogram-gallery.html) | ES680 pictogram catalog (1,466 blocks rendered from `pic_b.csn`) |

### `deploy/`

| File | Purpose |
|---|---|
| [`deploy/bootstrap.md`](deploy/bootstrap.md) | Hetzner CX22 bootstrap runbook for the drawlang editor deploy |

Deploy scripts and systemd units themselves live at the repo root under `deploy/`.

## Contributing

- Markdown is the source of truth for every document. Word (`.docx`) files, when present, are generated from the Markdown via `pandoc` and should not be edited directly.
- German technical vocabulary from the ES680 source (Pictogramm, Baustein, Konnektor, Rahmen, Raster, Maske) is preserved in Siemens spelling.
- Cite the source `.htm` page in `es680-damo/` when quoting the ES680 schema.
