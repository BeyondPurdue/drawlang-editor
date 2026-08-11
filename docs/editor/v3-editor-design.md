# Drawlang Editor — v3 Design Document

**Status:** DRAFT for approval — no code until you say yes.
**Author:** BM Global
**Language target:** Drawlang v0.6 (LOCKED, no new opcodes)
**Deployed today:** `b681130` on `editor.beyondpurdue.com`

This document is the single source of truth for the next editor. When you approve it, work starts step by step, one deliverable per step, waiting for your green light between each.

---

## 1. Guiding rules — non-negotiable

1. **API is the only path.** Every mark on every canvas is produced by a `POST` of one or more drawlang statements to a single endpoint. The graphical editor, the CLI, the voice/AI input all use exactly this endpoint. There is no other primitive.
2. **No new opcodes, ever.** Drawlang v0.6 stays locked. If a feature can't be expressed in v0.6, we discuss a formal extension before touching the spec — never a workaround in the editor.
3. **KISS.** Anything more complex than the simplest working answer needs to be justified. The default answer is the simple one.
4. **No vendor name appears in the public repo.** Anywhere. Comments, code, examples, tests, frames.
5. **Coordinates are drawlang-native.** Origin bottom-left, Y up, integer units.
6. **No decoration.** No stock icons, no gradients, no ornamentation. This is an engineering tool, not a design tool.

---

## 2. What the editor is

A single web application at `editor.beyondpurdue.com` with two main surfaces:

- **Canvas editor.** For building drawings by placing lines, shapes, text, and library symbols on a paper frame.
- **Library manager.** For creating and organizing reusable **Group Symbols** (motors, valves, frames, title blocks — anything).

Both surfaces are driven by the same drawlang, the same database, and the same API. The graphical editor is a client of the API. The AI is a client of the API. The CLI is a client of the API.

---

## 3. Coordinate system and grid

### 3.1 Native drawing coordinates

- Origin: **bottom-left**
- X: increases to the right
- Y: increases upward
- Units: integers, drawlang native (roughly 1 unit ≈ 1 point in output)
- A3 landscape total: **1223 × 679** drawlang units (matches current frame)
- A3 landscape useful inner drawing area (after border strip): **1080 × 540** units

**This is unchanged from drawlang v0.6 and current renderer. Nothing here moves.**

### 3.2 User-facing grid (28 × 14)

**Purpose:** Give the user a coarse, sayable coordinate ("G5") for placing things by mouse, keyboard, or voice. The server never sees "G5" — it only sees drawlang.

- **Columns:** 1..28, left to right
- **Rows:** A..N (14 letters, top to bottom), matching legacy engineering-drawing convention
- **Cell size:** 1080 / 28 ≈ **38.57 × 38.57 drawlang units — perfect squares**
- **Grid origin:** the useful inner drawing area's top-left corner, offset by the border strip
- **Cell "G5" resolves** to the center of column 5, row G, in drawlang coordinates

Simple resolver (client-side, in JS or Python):

```
CELL = 1080 / 28   # = 38.5714... drawlang units
INNER_LEFT   = 71  # left border strip width in drawlang units
INNER_BOTTOM = 71  # bottom border strip height in drawlang units
INNER_TOP    = 611 # 71 + 14*CELL

def resolve(cell):        # cell = "G5"
    row_letter, col_str = cell[0], cell[1:]
    row_idx = ord(row_letter) - ord('A')          # A=0..N=13
    col_idx = int(col_str) - 1                    # 1..28 -> 0..27
    x = INNER_LEFT   + (col_idx + 0.5) * CELL
    y = INNER_TOP    - (row_idx + 0.5) * CELL     # top-down for labels
    return int(round(x)), int(round(y))
```

**Frame border labels** on all four sides are updated to A..N × 1..28 in the frame drawlang program (Step 2).

### 3.3 Why the grid is client-side only

The server accepts only drawlang. If tomorrow you want a 40 × 20 grid, or a 56 × 28 grid for A2 paper, you change the client resolver — no server change, no spec change. The grid is a convenience, not a coordinate system.

---

## 4. The Group model — KISS

### 4.1 What a Group is on canvas

A Group is a run of drawlang statements on the canvas wrapped by two comment lines. Drawlang v0.6 already supports `#` comments; the renderer ignores them.

```
# group  name=motor  id=motor#1  origin=500,300
ma,500,300;dl,20,0;ci,5;tx,0,M;
# end group  id=motor#1
```

**Rules:**
- **The renderer treats these as normal drawlang.** It only draws. Comments are ignored.
- **The editor treats a `# group ... # end group` block as one selectable unit** — click any statement inside, the whole block is selected.
- **Move a group** → rewrite only the anchor `ma,X,Y;` on the first content line. All relative coordinates inside the block stay intact.
- **Delete a group** → remove the block (requires confirmation).
- **Edit group content** → open the block in the symbol editor; on save, replace the block in place.
- **Save this group as a library symbol** → copy the block with origin normalized to `0,0` into the library table.

No new opcode. No hidden format. Just drawlang and two comment lines.

### 4.2 What a Library Symbol is

A Library Symbol is a named, reusable drawlang program stored in the database. Table row:

| Column | Type | Meaning |
|--------|------|---------|
| id | int PK | |
| name | text unique | e.g. `motor`, `valve_globe`, `frame_a3_bmg` |
| category | text | e.g. `symbol`, `frame`, `title_block` |
| drawlang_source | text | The drawlang program with origin at `0,0` |
| bbox_x0, bbox_y0, bbox_x1, bbox_y1 | int | Computed once at save time, for thumbnails and hit-testing |
| thumbnail_svg | text | Auto-rendered at save time |
| created_at, updated_at | timestamp | |

**When the user places a Library Symbol on a canvas**, the editor:
1. Fetches the symbol's `drawlang_source`.
2. Wraps it in `# group name=<name> id=<name>#<n>  origin=X,Y` and `# end group id=<name>#<n>` markers.
3. Rewrites the leading `ma,0,0;` to `ma,X,Y;`.
4. POSTs the whole block to `/api/canvases/{id}/statements`.

**No back-reference from canvas to library.** If you later change the library symbol, existing canvas groups are not updated (Path A, spec-locked). To update a canvas group, re-drop the symbol.

### 4.3 Why this is enough

- One rule (comments as markers) does the whole job.
- Every canvas is still pure drawlang v0.6 — you can copy-paste it into any renderer.
- Semantic naming later (Section 8) just refines the `id=` field.
- Ungrouping a group is deleting its two comment lines. Grouping a selection is inserting two comment lines. That's it.

---

## 5. API surface

**All endpoints return JSON.** Errors carry `{ok:false, error, error_kind, statement_index}` per the current convention. Auth: session cookie (existing setup).

### 5.1 Canvases

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/canvases` | List canvases |
| POST | `/api/canvases` | Create canvas: `{name, template?}` where `template` is a library frame name |
| GET | `/api/canvases/{id}` | Get canvas metadata + rendered SVG |
| GET | `/api/canvases/{id}/source` | Get raw drawlang source |
| POST | `/api/canvases/{id}/statements` | **The one write endpoint** — append drawlang statements. Body: `{drawlang: "ma,500,300;dl,20,0;..."}`. Response includes new source, new SVG, statement indices added. |
| POST | `/api/canvases/{id}/undo` | Pop the last committed statement block (a group counts as one block). |
| DELETE | `/api/canvases/{id}/groups/{group_id}` | Delete one group (the block between markers). |
| PATCH | `/api/canvases/{id}/groups/{group_id}` | Move a group: `{origin_x, origin_y}` — rewrites only the anchor `ma`. |

### 5.2 Library

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/library` | List all symbols; supports `?category=frame` |
| POST | `/api/library` | Save a symbol: `{name, category, drawlang_source}` — auto-computes bbox + thumbnail |
| GET | `/api/library/{name}` | Get one symbol |
| PATCH | `/api/library/{name}` | Update a symbol; re-computes bbox + thumbnail; existing canvas groups are unaffected |
| DELETE | `/api/library/{name}` | Delete symbol (requires confirmation client-side) |

### 5.3 Export

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/canvases/{id}/export.svg` | Rendered SVG |
| POST | `/export/pdf` | Existing endpoint, unchanged (paper-fill + landscape sizing fixed in b681130) |

### 5.4 Voice-to-drawlang (Section 7)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/interpret` | Body: `{text, canvas_id}`. Returns `{drawlang, explanation}`. Does NOT execute — the client shows the proposal and the user confirms before it's POSTed to `/statements`. |

---

## 6. UI wireframes

### 6.1 Canvas editor

```
+----------------------------------------------------------------------------+
| BM Global · Drawlang Editor · Canvas: <name>            [Save] [Export ▾]  |
+---------+-----------------------------------------------+------------------+
| TOOLS   |                                               | LIVE DRAWLANG    |
|         |                                               |                  |
| [ ↖ ]   |                                               | Hover:           |
| [ / ]   |                                               | ma,500,300;      |
| [ □ ]   |         (Canvas SVG rendered here)            | dl,120,0;        |
| [ ○ ]   |                                               |                  |
| [ ⌒ ]   |         Grid overlay: A..N × 1..28            | ─────────────    |
| [ ~ ]   |         (toggle button)                       |                  |
| [ T ]   |                                               | COMMITTED (log)  |
|         |                                               | 1. ma,71,540;    |
| [ ⇥ ]   |                                               | 2. dl,1080,0;    |
| Library |                                               | 3. dl,0,-540;    |
| ▸ frames|                                               | ...              |
| ▸ symb. |                                               |                  |
| ▸ text  |                                               | ─────────────    |
|         |                                               |                  |
| Undo    |                                               | 🎤 Voice input   |
| Redo    |                                               | (click, speak)   |
|         |                                               |                  |
+---------+-----------------------------------------------+------------------+
```

- **Left toolbar:** primitives (line, rectangle, circle, arc, bezier, text), plus a library-symbol picker (expandable tree).
- **Center:** SVG canvas with the frame + committed statements rendered. Grid overlay toggle (A..N × 1..28) is a client-side visual aid.
- **Right panel:**
  - **Hover bubble** at the top shows the drawlang for the gesture in progress, updated in real time.
  - **Committed log** shows every statement that has actually landed on the canvas, numbered.
  - **Voice input button** at the bottom.

### 6.2 Live drawlang bubble — behavior

- **Line tool.** User clicks at `(100, 200)`, moves cursor to `(340, 200)`. Bubble reads `ma,100,200;dl,240,0;`. Values update every frame as cursor moves. On release, that exact string is POSTed.
- **Circle tool.** User clicks at `(500, 300)`, drags to `(510, 300)`. Bubble reads `ma,500,300;ci,10;`. On release, POSTed.
- **Text tool.** User clicks at `(600, 400)`, types `MOTOR`, chooses angle 0. Bubble reads `ma,600,400;tz,7;tx,0,MOTOR;`. On Enter, POSTed. If user presses Shift+Enter mid-typing, a new line becomes a second `tx` at an offset the editor computes automatically.
- **Library symbol drop.** User drags `motor` from the library, drops at `(500, 300)`. Bubble reads:
  ```
  # group  name=motor  id=motor#3  origin=500,300
  ma,500,300;dl,20,0;ci,5;tx,0,M;
  # end group  id=motor#3
  ```
  On drop, whole block POSTed.

### 6.3 Grid label direction and origin

- Grid cells indexed **A (top row) → N (bottom row)** for readability matching printed A3 drawings.
- **Cell "A1"** is the top-left inner cell.
- **Cell "N28"** is the bottom-right inner cell.
- **Cell "G5"** — the example you gave — resolves to column 5, row G, cell center, in drawlang `(x, y)`.
- **`ma,0,0;` in drawlang is the bottom-left of the paper, not the grid.** This does not change. The grid is a coordinate skin over drawlang, nothing more.

### 6.4 Library manager

```
+----------------------------------------------------------------------------+
| BM Global · Drawlang Editor · Library                     [+ New symbol]   |
+----------------------------------------------------------------------------+
| Category:  [All ▾]   Search: [__________]                                  |
+----------------------------------------------------------------------------+
|                                                                            |
|  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐                            |
|  │ frame  │  │ frame  │  │ symbol │  │ symbol │                            |
|  │  A3    │  │  A4    │  │ motor  │  │ valve  │                            |
|  │  BMG   │  │  BMG   │  │        │  │ globe  │                            |
|  └────────┘  └────────┘  └────────┘  └────────┘                            |
|  frame_a3_  frame_a4_    motor       valve_globe                           |
|  bmg        bmg                                                            |
|                                                                            |
+----------------------------------------------------------------------------+
```

- Each tile is an auto-rendered SVG thumbnail of the symbol's own drawlang.
- Click a tile → opens the symbol in the canvas editor with its `drawlang_source`. Saving overwrites the library entry.
- "+ New symbol" opens an empty symbol-editing canvas.

---

## 7. Voice / AI input

### 7.1 UX

- Right panel, bottom: 🎤 button.
- Click → browser Web Speech API starts recording.
- Speak: "Draw a circle diameter 5 at G5".
- Release → text transcript appears in the bubble.
- Text is POSTed to `/api/interpret` along with the current `canvas_id`.
- Server calls the AI to translate text → drawlang. Returns proposed drawlang + short explanation.
- Bubble shows: `Proposed: ma,257,553;ci,2.5;   Explanation: Circle radius 2.5 centered at G5.`
- User clicks **Accept** → the proposal is POSTed to `/api/canvases/{id}/statements`.
- User clicks **Reject** or edits the text → no side effect on the canvas.

### 7.2 Rules the interpreter follows

1. Output is **only drawlang v0.6**. If the request can't be expressed in v0.6, reply with `{ok:false, error:"..."}`.
2. If the request references a grid cell (`G5`, `C12`), resolve using the client's grid convention (Section 3.2).
3. If the request references a library symbol by name (`motor`, `valve_globe`), the interpreter emits the `# group ... # end group` block per Section 4.
4. **The interpreter never invents symbols.** If `motor` isn't in the library, it replies with `{ok:false, error:"symbol 'motor' not in library"}`.
5. **No text is drawn implicitly.** If the user says "put a motor at G5", only the motor drawlang is emitted — no label added unless the user asked for one.

### 7.3 CLI parity

Everything voice can do, the CLI can do by POSTing text to `/api/interpret`. Everything the AI (me, in this session) can do, the browser voice input can do. Same endpoint, same rules.

---

## 8. Semantic naming by location — future chapter (documented, not built)

**Intent.** Once a drawing has a frame and grouped symbols, each group's `id=` field should be automatically named from its position on the frame grid, so tools and humans can refer to symbols semantically instead of by anonymous numbers.

Example: a `motor` group placed such that its origin resolves to grid cell G5 on page 1 of a drawing would get:

```
# group  name=motor  id=motor_p1_G5  origin=257,553
```

**Algorithm sketch:**
1. When a group is committed to a canvas, resolve its origin `(X, Y)` back to the nearest grid cell.
2. Compose `id = <name>_p<page>_<cell>`.
3. Ensure uniqueness within the canvas by appending `#2`, `#3` etc. only when two groups of the same name land in the same cell.

**Why this is not built now.** It's a rename that touches the group model but not the API or the language. Building the editor first gives us real drawings to test the naming heuristic against. Adding it later is one function, zero spec impact.

---

## 9. Renaming and scrubbing plan

### 9.1 Rename

- **Concept**: the group-of-drawlang-statements idea is called simply **Group**.
- **Class/file names in public repo** using a vendor namespace are renamed to neutral names. This scrub is complete in Step 1.
- Private research repo is not touched.

### 9.2 Scrub (completed in Step 1)

- Vendor references removed from every file (README, docs, spec, spec history, code, comments, tests, diagrams, frames).
- Trademark disclaimer removed from README and spec entirely.
- Vendor company name on both A3 frames replaced with "BM Global A.S.".
- `.egg-info/` and `.pytest_cache/` build artifacts removed from disk.

### 9.3 Commit and deploy

- One commit for the full Step 1 scrub. Deploy timer picks it up. `/health` reports the new SHA.

---

## 10. Data model

### 10.1 SQLite tables (added to existing DB)

```sql
CREATE TABLE canvases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  drawlang_source TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE library_symbols (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL DEFAULT 'symbol',
  drawlang_source TEXT NOT NULL,
  bbox_x0 INTEGER, bbox_y0 INTEGER, bbox_x1 INTEGER, bbox_y1 INTEGER,
  thumbnail_svg TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**No group-instance table.** Groups live inside `canvases.drawlang_source` as `# group ... # end group` blocks. Simpler, one source of truth per canvas.

---

## 11. Step-by-step execution plan

I go through these in order. **After each step I stop and show you the result. You approve, I move to the next.**

1. **Rename + scrub.** Remove vendor names from the public repo. Rename group concept to `Group`. Done in a single commit; verify with diff before deploy.
2. **Frame rewrite (v3).** Rewrite `frames/a3-empty.drawlang`:
   - Replace border label grid with **A..N × 1..28** (28 columns, 14 square rows, cells ~38.57 units).
   - Fix copyright block (no commas inside strings; correct top-to-bottom line order).
   - Replace vendor name with "BM Global A.S." (already in your uploaded revision).
   - Save frame to `library_symbols` as `frame_a3_bmg` (category=`frame`).
   Deliverable: new PDF preview for you to visually approve.
3. **DB schema + read-only API.** Add `canvases` and `library_symbols` tables. Ship `GET /api/canvases`, `GET /api/library`, `GET /api/canvases/{id}`. No writes yet.
4. **Statement-write API.** Ship `POST /api/canvases/{id}/statements` with parse-validate-commit, `POST /api/canvases/{id}/undo`, and group delete/move endpoints.
5. **Library CRUD API.** Ship `POST /api/library`, `PATCH /api/library/{name}`, `DELETE /api/library/{name}` with thumbnail auto-render.
6. **Canvas editor UI.** Toolbar + canvas + live drawlang bubble + committed log + grid overlay. Line/rectangle/circle/text tools. Save/Export.
7. **Library manager UI.** Grid of thumbnails, category filter, click-to-edit, +New.
8. **Library symbol drop.** Drag from library onto canvas → group block committed via API.
9. **Voice + AI input.** 🎤 button → Web Speech API → `/api/interpret` → propose-accept flow.
10. **Semantic-naming chapter in docs.** One page, no code.

Each step is ~1 to 2 half-day sessions of work with tests. Total: ~2 weeks of focused work if we stay disciplined.

---

## 12. What is deliberately not in this document

- **Multi-page projects.** For now, one canvas = one drawing. When you need multi-page, we'll add a `projects` table and page ordering — no other change needed.
- **Version history per canvas.** Not in v3. Undo works within a session; permanent versioning is a later addition.
- **Access control.** Assumes the editor is behind existing session auth. Multi-user editing on the same canvas is not attempted.
- **Import of legacy plans.** The analysis viewer we already have stays as-is at `/plans`. It is not part of the editor.
- **New drawlang opcodes.** Not now, not later. Section 1 rule 2.

---

## 13. Open questions I still need answered

None. Everything you told me in the last three messages is captured above. If you spot anything I got wrong, tell me and I'll patch this document before writing any code.

**When you are ready, reply with either:**
- "Approved, start Step 1" — I begin the rename and scrub.
- Corrections or additions — I revise the document and re-post.
