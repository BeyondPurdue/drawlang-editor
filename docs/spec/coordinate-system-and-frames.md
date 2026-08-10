# 07 — Coordinate System, Units, and Frames

**Status:** authoritative reference (2026-08-10). Supersedes the "1 px = 1 SVG unit" assumption in `06-render-architecture.md`.

**Purpose:** define exactly what the numbers in a `cmd` program mean, how they map to physical paper, and what role the `frame` and `raster` tables play. Every renderer (SVG, PostScript, PDF, CGA screen) must obey this model or it will not replicate ES680.

---

## 1. Summary — the single most important fact

**ES680 does not store a fixed language-unit → millimetre ratio anywhere in the database.**

Coordinates inside a `cmd` program (pic_b.cmd, pic_ex.cmd) are **abstract plotter pixels**. They have no inherent physical size. The mapping to real paper (mm, points, inches) is derived **at render time** from three inputs:

1. The **frame** the drawing lives on — `frame.gu_x, gu_y, go_x, go_y` define a pixel window (lower-left → upper-right corner of the grid area).
2. The **paper format** chosen for the print job — `pr_queue.format` (`A3`, `A4`, ...).
3. The **paper margins** used by the plotter driver.

The renderer computes an affine transform (frame pixels → paper mm) and uses it for every stroke. On a different paper size, the same `cmd` program produces a proportionally smaller or larger drawing.

**Consequence:** any renderer that hardcodes a scale ("1 unit = 0.35 mm", "1 unit = 1 SVG unit at 96 DPI", "viewBox = 0 0 1191 801") will render frames 2, 10, and 30 wrong, will render everything wrong on A4 or A2 paper, and will render bare symbols (pic_ex with no frame context) at an arbitrary size.

---

## 2. Source evidence

### 2.1 `raster.offset` column definition

From `extracted-html/kap2_2/raster.htm`:

> `offset  i2  Abstand vom 0-Punkt in Pixeln (0-Punkt befindet sich links unten)`
> *"Distance from origin in pixels (origin is at lower-left)."*

The word used is **Pixeln** — pixels. Not millimetres, not points, not typographic units. And the origin is **lower-left** (mathematical convention, not screen convention). This applies to every coordinate the interpreter sees.

### 2.2 `frame` table schema

From `extracted-html/kap2_2/frame.htm`:

```
frm_id    i2  Rahmen-Id
pa_x,pa_y i2  x/y position of texts in the LEFT margin
pe_x,pe_y i2  x/y position of texts in the RIGHT margin
gu_x,gu_y i2  x/y of the LOWER-LEFT grid corner   (gu = Gitterpunkt unten)
go_x,go_y i2  x/y of the UPPER-RIGHT grid corner  (go = Gitterpunkt oben)
ln_x,ln_y i2  row/column spacing on this plan
```

**Every value in this row is a pixel offset from the plotter canvas origin (0, 0) at lower-left.** The `frame` row does not carry a paper-size field.

### 2.3 `pic_ex` — frames are stored as negative pic_ids

From `extracted-html/kap2_2/pic_ex.htm`:

> `pic_id  i2  Identifikation von Pictogrammen; ... Negative pic_id's beschreiben Formulare/Rahmen (pic_ex, pic_b; d.h. pic_ex.pic_id bzw. pic_b.pic_id = -frame.frm_id)`
> *"Negative pic_id values describe forms/frames — pic_ex.pic_id (or pic_b.pic_id) = -frame.frm_id."*

So `pic_ex -10` is the pen program for `frame 10`. `pic_ex -1` = `frame 1`, `pic_ex -20` = `frame 20`, `pic_ex -30` = `frame 30`. The program draws the frame's border, tick marks, and title-block outlines **in the same pixel coordinate space as the frame itself uses for gu/go**.

### 2.4 `pic_ex.cmd` — the invisible print-segment rectangle

From `extracted-html/kap2_2/pic_ex.htm`:

> `Erste Graphik-Anweisung bei atmenden Bausteinen: rt,i — Beschreibt die Segmentgröße (für Drucker) und ist unsichtbar`
> *"First graphics instruction for expanding blocks: rt,i — describes the segment size (for the printer) and is invisible."*

This is the block's own **printable extent** carried inside the program. The interpreter must recognise the `i` modifier and treat that rectangle as metadata (page bounds), not as visible geometry.

### 2.5 Paper format is a print-job property, not a drawing property

From `extracted-html/kap2_3/pr_queue.htm`:

```
printer  vch10  Name des Druckers, auf dem gedruckt werden soll (z.B. cx, ...)
format   vch5   Papier-Format, z.B. A4, A3, ...
```

Paper size is chosen when the plan is queued for print. The same plan can print on A4 today and A3 tomorrow; the `cmd` programs don't change.

---

## 3. The nine frames actually present in the database

From `frame.csn` (the entire table — 9 rows):

| frm_id | pa_x | pa_y | pe_x | pe_y | gu_x | gu_y | go_x | go_y | ln_x | ln_y | grid W × H (px) |
|-------:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|:----------------|
|  1 | 1040 | 128 | 25 | 128 |  48 |  66 | 1239 | 867 | 12 | 12 | **1191 × 801** |
|  2 |  953 | 131 | 75 | 131 | 355 | 142 |  943 | 817 | 12 | 25 | **588 × 675** |
|  3 | 1040 | 128 | 25 | 128 |  48 |  66 | 1239 | 867 | 12 | 12 | **1191 × 801** |
|  4 | 1040 | 128 | 25 | 128 |  48 |  66 | 1239 | 867 |  5 |  5 | **1191 × 801** |
|  5 | 1040 | 128 | 25 | 128 |  60 |  66 | 1239 | 867 | 25 | 25 | **1179 × 801** |
|  6 | 1040 | 128 | 25 | 128 |  60 |  66 | 1239 | 867 | 25 | 25 | **1179 × 801** |
| 10 |  953 | 131 | 75 | 131 | 355 | 142 |  942 | 817 | 12 | 25 | **587 × 675** |
| 20 | 1040 | 128 | 25 | 128 |  48 |  66 | 1239 | 867 | 12 | 12 | **1191 × 801** |
| 30 |  953 | 131 | 75 | 131 | 355 | 142 |  943 | 817 | 12 | 25 | **588 × 675** |

Two clear families:

- **Family A — landscape "big" frame** (frames 1, 3, 4, 5, 6, 20). Grid ≈ 1191 × 801 pixels. Text-block anchor at pa=1040. Consistent with a **standard FUP plan** intended to print landscape on A3.
- **Family B — portrait-ish "small" frame** (frames 2, 10, 30). Grid ≈ 588 × 675 pixels. Text-block anchor at pa=953. Consistent with a **secondary plan type** (likely single-line / P&ID sheets or half-page plans).

The `ln_x/ln_y` differences within Family A (12/12 vs 5/5 vs 25/25) select the grid density (1×, 2.4×, 0.48×) — same window, different subdivisions.

---

## 4. The `raster` table — plan coordinate labels

`raster` supplies the **printed labels** for the coordinate grid — rows A/B/C/… on the vertical axis, columns 1/2/3/… on the horizontal axis. From `raster.csn` (excerpt for `frame_id=2, pro_id=1, spra=g3` — the family-B frame):

```
frame_id  pro_id  spra   orient  titel  offset
    2        1     g3      y      1A     892
    2        1     g3      y      1B     742
    2        1     g3      y      1C     592
    2        1     g3      y      1D     442
    2        1     g3      y      1E     317
    2        1     g3      y      1F     167
    2        1     g3      x      11     163
    2        1     g3      x      12     319
    2        1     g3      x      13     475
    2        1     g3      x      14     631
    2        1     g3      x      15     787
    2        1     g3      x      16     943
    2        1     g3      x      17    1099
    2        1     g3      x      18    1255
```

- **x-axis labels** `11..18` at pixel offsets 163, 319, 475, 631, 787, 943, 1099, 1255 → column spacing 156 px.
- **y-axis labels** `1A..1F` at pixel offsets 892, 742, 592, 442, 317, 167 → row spacing 150 px (with a compressed A→B step).

These are the ANSI/ISO-style plan reference labels the plotter draws in the margins. `raster` is **not** the coordinate system itself — that lives in `frame`. `raster` is only the label overlay.

---

## 5. The render-time transform (specification)

Given:

- `F` — a `frame` row (fields `gu_x, gu_y, go_x, go_y`),
- `P` — a chosen paper size in millimetres (width `Pw_mm`, height `Ph_mm`), e.g. A3 landscape = (420, 297),
- `M` — the plotter's paper margins in millimetres (`ml`, `mr`, `mt`, `mb`),

the renderer computes the affine `pixel → mm` transform:

```
usable_w_mm = Pw_mm - ml - mr
usable_h_mm = Ph_mm - mt - mb
grid_w_px   = F.go_x - F.gu_x        # e.g. 1191 for frame 4
grid_h_px   = F.go_y - F.gu_y        # e.g.  801 for frame 4

sx = usable_w_mm / grid_w_px         # mm per pixel, x
sy = usable_h_mm / grid_h_px         # mm per pixel, y

x_mm(px) = ml + (px - F.gu_x) * sx
y_mm(px) = mb + (px - F.gu_y) * sy   # y grows UP; both frame and paper use lower-left origin
```

If `sx ≠ sy` the drawing would distort. In practice the plotter driver either preserves aspect ratio (choosing the smaller of `sx, sy` and centring the plan on the paper) or accepts distortion — this needs to be verified against actual ES680 plots, but the safe default for our renderer is **preserve aspect ratio**.

For **Frame 4 on A3 landscape** (420 × 297 mm), typical plotter margins ≈ 10 mm all round:

```
usable_w = 420 - 20 = 400 mm
usable_h = 297 - 20 = 277 mm
grid_w   = 1191 px
grid_h   = 801 px
sx = 400 / 1191 ≈ 0.3359 mm/px
sy = 277 / 801  ≈ 0.3458 mm/px
```

Picking the smaller (aspect-preserving) scale ≈ **0.336 mm per pixel**. This is close to my earlier "0.35 mm/px" guess but is now derived, not assumed, and it changes on a different paper size.

For **Frame 10 on A3 landscape** the same computation gives ≈ 0.672 mm/px — frame 10 draws twice the physical size per pixel because its grid window is half as wide.

---

## 6. Symbols with no owning frame

`pic_ex` rows with **positive** `pic_id` are symbols (blocks, expandable blocks). They are placed on plans via `obj_g` / `obj_f`, and the **plan's frame** provides the coordinate window. When the FUP editor renders a symbol standalone in a palette (e.g. pic_ex 1511 shown in the pictogram bar), it is rendered against a **default palette frame** — small pixel window, high magnification.

For our replica editor, when previewing a bare symbol without a plan context, the renderer must pick a default frame explicitly (candidate: frame 4). The choice must be recorded in the `PageDescription`, not hidden in the SVG backend.

---

## 7. The `i` modifier on `rt` (invisible print-segment rectangle)

The interpreter must implement the `i` (invisible) modifier on `rt`. When present:

- The rectangle is **not** drawn as a stroke.
- Its dimensions are recorded on the current page as the **printable segment size** for expanding blocks (`atmende Bausteine`). Downstream tools (print driver, PDF generator) use this to decide page breaks and clipping regions.

Any pre-existing behaviour that skipped `i` or treated it as a "hidden" boolean without recording the dimensions is incorrect.

---

## 8. Model corrections against earlier notes

- **`06-render-architecture.md` line 76:** *"Assume 1 px = 1 SVG unit initially; add pic_b.sc scale factor for palette rendering."* — This oversimplifies. `pic_b.sc` is a symbol-level scale for palette rendering only; the plan-level scale comes from `frame.gu/go` mapped to paper. Both must compose.
- **`05-cmd-mini-language.md` line 24:** *"Units: pixels (per the schema; treated as logical device units in practice)."* — Correct in spirit but incomplete. The "logical device" is the plotter canvas, and the mapping to physical paper is per-frame and per-paper-format, not global.

Both files should be updated to cross-reference this note.

---

## 9. Implications for the intermediate `PageDescription` layer

The `PageDescription` type must carry:

- **`frame_id`** and the full `frame` row (`gu, go, pa, pe, ln`) — pixel window definition,
- **`paper_format`** (default A3 landscape; overridable per-render),
- **`margins_mm`** (per paper format; default 10 mm),
- **`primitives`** — list of `MoveTo / LineTo / Rectangle / Circle / Arc / Text / ...` each carrying `(x_px, y_px)` in the frame's pixel coordinates (NOT pre-multiplied to mm),
- **`print_segment`** — optional rectangle from the `rt,i` metadata, in pixel coordinates,
- **`palette_scale`** — optional per-symbol `pic_b.sc` factor.

The three backends translate this at emit time:

- **PostScript backend:** compute `sx, sy` at emit time; emit `%%BoundingBox`, `/inch { 72 mul } def` scale block, then `moveto / lineto / rectstroke / ...` in points (1 pt = 1/72 inch, so mm→pt via `× 72/25.4`).
- **PDF backend:** either identical to PostScript (then run through `ps2pdf`), or use a Python PDF library and apply the same `sx, sy` transform.
- **SVG backend:** set `<svg width="{Pw_mm}mm" height="{Ph_mm}mm" viewBox="0 0 {Pw_mm} {Ph_mm}">` and emit primitives in mm; the browser then displays them at real physical size.

Note that **the SVG backend never chooses its own viewBox from bbox heuristics**. The viewBox is dictated by the paper size, exactly as PostScript's `%%BoundingBox` is.

---

## 10. Open items

1. **Verify plotter margins.** The 10 mm default is a placeholder — real ES680 plotter driver config should be checked (search for `.pl` config files or plotter-init scripts in the backup snapshots).
2. **Verify aspect-ratio behaviour.** Confirm whether the plotter driver stretches to fit or preserves aspect ratio and centres. A single real ES680 A3 plot side-by-side with our replica render will settle this.
3. **Verify default paper format per frame family.** Family A frames (1191×801, aspect ≈ 1.487) fit A3 landscape (420/297 ≈ 1.414) with a small aspect mismatch — likely aspect-preserving fit. Family B frames (~588×675, aspect ≈ 0.87) are portrait — probably A4 portrait (210/297 ≈ 0.71) or a half-A3.
4. **Locate the plotter driver's paper table.** ES680 must map "A3" → 420 × 297 mm somewhere; find that table (probably a system-level config, not an Ingres table).
5. **Verify the `i` modifier's exact semantics on `rt`.** Confirm from source scripts (`txpExtractData.pl` etc.) whether `rt,i` sizes are always symbol-local coordinates or plotter-canvas coordinates.
