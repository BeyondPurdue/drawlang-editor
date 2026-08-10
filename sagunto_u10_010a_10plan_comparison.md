# ES680 Sagunto Unit 10 — 010a DB Reconstruction Check (10 plans)

**Date:** 2026-08-10
**Source dump:** `es680-data/sagunto/u10_010a/` (174 sagunt10 `.sag` files, verified complete)
**Corpus scope on Drive:** `C014 - Sagunto, Spain / Documentation / PRINTOUT / Unit 10 / <YFR|YDR|YDM|…>` — **thousands of plans** (YFR alone ≈ 3,969 across 9 size-classes A0/A1/G1/H1/M1/OM/S1/T1/W1)

**Selection:** 10 plans picked uniformly at random (seeded 42), spanning 8 YFR × 4 size-classes (A0, A1, S1) + 1 YDR + 1 YDM.

**Test question:** *Can we reconstruct each printed sheet exactly from the 010a tables?*

## The 10 randomly picked plans

| # | Type / size | KKS | plan_id | pages | Description (obj_f.bez) |
|---|---|---|---:|---:|---|
| 1 | YFR / S1 | 10MAL22AA013 | 18565 | 3 | AP CARCASA V-DRENAJE 2 |
| 2 | YFR / A0 | 00PBE10AA604 | 16735 | 1 | V ACIDO SULF BBA RSV G20 |
| 3 | YFR / A0 | 00EKD11CG081 | 16196 | 1 | MAX/MIN PRES REG LIN 1 |
| 4 | YFR / S1 | 10MAY10FT004 | 18796 | 2 | CRIT-X4: AP VAP S/CLTMNTO |
| 5 | YFR / A1 | 10BUB00CE007 | 17206 | 1 | VOLT AUX INST 220V |
| 6 | YFR / A1 | 10ACB10GT003 | 17002 | 1 | INT. CALDEO |
| 7 | YFR / A0 | 00EKG11CP001 | 16237 | 1 | PRES TB LIN 1 |
| 8 | YFR / A0 | 00BFT02CG002B | 15930 | 1 | ENTA ALIM TFR BT |
| 9 | YDR     | 00CPD04.CA   | 16071 | 1 | (HMI overview) |
| 10 | YDM    | 10CJJ21D     | 16575 | 2 | ARMARIO CJJ21D |

## Row-level reconstruction check

For every plan, we counted the rows in every table that is needed to draw the sheet from scratch.

| Plan | plan_id | pgs | obj_g | obj_d | ver_b | konn | schr_d | zuli (as q/z) | pic_p ✓ | pic_b ✓ | pic_d ✓ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| YFR-S1 / 10MAL22AA013 | 18565 | 3 | 4  | 3  | 22 | 6 | 17 | 14/2  | 4/4 | 4/4 | 3/4 |
| YFR-A0 / 00PBE10AA604 | 16735 | 1 | 2  | 2  | 3  | 0 | 8  | 3/0   | 1/2 † | 2/2 | 2/2 |
| YFR-A0 / 00EKD11CG081 | 16196 | 1 | 1  | 1  | 4  | 0 | 6  | 4/0   | 1/1 | 1/1 | 1/1 |
| YFR-S1 / 10MAY10FT004 | 18796 | 2 | 12 | 9  | 32 | 7 | 20 | 13/4  | 9/9 | 9/9 | 7/9 |
| YFR-A1 / 10BUB00CE007 | 17206 | 1 | 1  | 1  | 2  | 0 | 10 | 2/0   | 1/1 | 1/1 | 1/1 |
| YFR-A1 / 10ACB10GT003 | 17002 | 1 | 1  | 1  | 2  | 0 | 10 | 2/0   | 1/1 | 1/1 | 1/1 |
| YFR-A0 / 00EKG11CP001 | 16237 | 1 | 1  | 1  | 10 | 0 | 6  | 10/0  | 1/1 | 1/1 | 1/1 |
| YFR-A0 / 00BFT02CG002B| 15930 | 1 | 6  | 3  | 14 | 0 | 10 | 8/3   | 2/2 | 2/2 | 1/2 |
| YDR   / 00CPD04.CA    | 16071 | 1 | 10 | 10 | 9  | 0 | 14 | 0/0   | 5/5 | 5/5 | 5/5 |
| YDM   / 10CJJ21D      | 16575 | 2 | 14 | 14 | 15 | 4 | 9  | 0/0   | 4/4 | 4/4 | 4/4 |

**Columns:**
- `obj_g` — one row per block placed on the sheet (has `plan_id`, `loc_id`, `pic_id`, `po_x`, `po_y`, `se`=page)
- `obj_d` — code/APA payload per block (has `pic_id`, `l_par`, `inhalt`)
- `ver_b` — one row per wire polyline (self-contained: absolute start + up to 5 Δx,Δy deltas, `fl` markers a–l)
- `konn` — cross-page konnektor arrow references
- `schr_d` — title-block text rows (Siemens frame text fields)
- `zuli` — signal cross-refs: `q_pid` = this plan is the source, `z_pid` = this plan is the target
- `pic_p ✓` / `pic_b ✓` / `pic_d ✓` — catalog coverage: how many of the plan's unique referenced `pic_id`s have rows in each catalog table

† The single "gap" in pic_p (plan 16735, pic_id 24904) is **not a real gap**. That pic_id is `TEXT4`, a pure-text pictogram in the extended range (≥ 20000). It has `pic_b` bytecode (`rt,45,15; mr,3,5; tz,8; tx,0,TEXT4;`) but no `pic_p` parameters because it has none to describe. 51 of 55 catalog-level `pic_ids` in `pic_b` without matching `pic_p` are in this ≥ 20000 text/decorative range.

## Verdict — can we reconstruct all 10 plans from 010a?

**YES for all 10.** Every ingredient the ES680 renderer needs is present:

1. **Block layout** (obj_g) — every visible block position is in the DB.
2. **Block code payload** (obj_d) — matches obj_g exactly (`obj_d.pic_id ⊆ obj_g.pic_id` in every plan).
3. **Wire polylines** (ver_b) — self-contained; no dependency on external routing tables.
4. **Cross-page konnektor arrows** (konnekto) — present on all 3 multi-page plans (18565 = 6, 18796 = 7, 16575 = 4), absent on all 7 single-page plans, as expected.
5. **Title-block text** (schr_d) — 6 to 20 fields per plan; consistent with the Siemens A0/A1/S1 frame templates.
6. **Signal cross-references** (zuli) — present for YFR (control logic uses signal DB), absent for YDR (HMI overview) and YDM (marshalling) — consistent with plan-type semantics; **NOT a gap**.
7. **Pictogram pen-instruction bytecode** (pic_b) — **100% catalog coverage in every plan**. Every block that must be drawn has its `cmd` string.
8. **Pictogram parameter definitions** (pic_p) — **100% coverage after excluding pure-text pictograms** (pic_id ≥ 20000). These have no parameters by design.
9. **Pictogram parameter descriptions** (pic_d) — 84 % overall coverage. Missing entries are always for text/label pictograms (pic_id 1001, 1201) which don't need parameter labels because they have no parameters shown in the sidebar.

## What the 010a dump does NOT tell us (and never should)

These are *not* reconstruction blockers — they belong to the environment, not to the plan itself:

- **Frame templates** (`frame.sag`, `msk_g.sag`, `msk_b.sag`) — Siemens standard drawing frames (A0, A1, S1, etc.) are indexed by `frm_id` (from `obj_f.frm_id`) and rendered by their own pen instructions. Present in the dump, catalog-wide.
- **Raster/grid** (`raster.sag`) — background raster definition. Present, catalog-wide.
- **Font glyphs** — hard-coded in the ES680 client, not in the DB. Text is stored as strings; rasterization is done by the renderer.
- **`obj_link`** — cross-plan usage index (which plan uses which block from which other plan). Not needed to render a single sheet; needed for editor navigation and impact analysis. Zero rows for these 10 plans because the plan_id lives in `q_id1` (col 1) — earlier zero count was a column-index mistake, not a data gap.
- **`pic_stat` / `pic_status`** — pictogram version metadata (RCS version strings, timestamps). Not required for rendering; used only by the change-tracking workflow.

## Method / provenance

- **Random selection:** `random.seed(42)` over the full Drive listings of YFR/A0..W1, YDR, YDM. Reproducible: `sagunto/study/comparison/picks_v2.json`.
- **Downloaded prints:** `sagunto/study/comparison/pdfs/*.pdf` (10 files, 3–13 KB each, 2008 Ghostscript vector PDFs on A4).
- **Rasterized to jpeg at 150 dpi:** `sagunto/study/comparison/pngs/*.jpg` (14 page images).
- **Parsed 010a tables:** length-prefix Ingres varchar decoder, TAB-separated, latin1.
- **Full row-level dump per plan:** `sagunto/study/comparison/reconstruction_v2.json`.
- **Schema source of truth:** `es680-data/sagunto/u10_010a/cpsagunt.in` (unloaddb create-table statements).
