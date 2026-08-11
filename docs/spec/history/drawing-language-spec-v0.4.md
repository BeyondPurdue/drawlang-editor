# Drawing Language Specification

**Project:** Drawlang Drawing System — Universal Vector Drawing Editor
**Owner:** BM Global
**Document status:** LOCKED v0.4 — frozen 2026-08-09. Any change requires a new version (v0.5).

**Change from v0.3 → v0.4:** the `dl` opcode now accepts the `i` (invisible) modifier, matching the pattern already established by `rt`. An invisible line advances the pen from its current position to the endpoint `(x+dx, y+dy)` and contributes both endpoints to the bounding-box accumulator, but emits no visible mark. This is an additive, backward-compatible change — every v0.3 program remains a valid v0.4 program. Rationale: real legacy pic_ex programs use `dl,dx,dy,i` extensively (≈10% of the imported pic_ex library, 138 occurrences in a single 548-placement plan) to reserve symbol bounding-box extents without visible strokes. The v0.3 spec unnecessarily rejected these programs; conceptually `i` on `dl` behaves exactly as `i` on `rt`.

**Change from v0.2 → v0.3:** the FLOAT numeric type is removed. The language now has a single numeric type, INT (signed 16-bit). Every argument that v0.2 declared as FLOAT (`tx` angle, `ar` start and sweep) is now declared as INT. A literal written with a decimal point (`0.`, `90.`, `3.14`) is still accepted and is rounded half-toward-positive-infinity to the nearest integer. Every v0.2 program that used only whole-degree angles — which is every real legacy program — remains a valid v0.3 program. Rationale: the 12,712 numeric-angle values in the legacy backup are all whole degrees; not one is fractional. Sub-degree precision has no meaning on a technical schematic (1° tilt of a 100 mm label = 1.75 mm drift, below print resolution). Removing FLOAT collapses two numeric types into one, eliminates the emitter ambiguity that caused the Frame guide LexicalError, and matches the source system.

**Change from v0.1 → v0.2:** §3.5 now defines a line-comment syntax (`#` to end of line). This is an additive, backward-compatible change — every v0.1 program remains a valid v0.2 program. Rationale: templates and human-authored programs need somewhere to record source, intent, and provenance, which is a principle called out in §1.2.6 ("human-writable and human-readable").
**Purpose:** Define the complete, self-contained mini-language that describes every visible mark on every drawing produced by this system. This document is the single source of truth for the language grammar, semantics, and interpretation. Both AI systems and human developers must be able to read this specification and implement a fully compliant interpreter without reference to any external system.

---

## Table of Contents

1. [Overview and Design Principles](#1-overview-and-design-principles)
2. [Notation Used in This Document](#2-notation-used-in-this-document)
3. [Lexical Structure](#3-lexical-structure)
4. [Coordinate System and Units](#4-coordinate-system-and-units)
5. [Pen State Model](#5-pen-state-model)
6. [Core Opcodes (Basics)](#6-core-opcodes-basics)
7. [Extension Opcodes](#7-extension-opcodes)
8. [Modifiers](#8-modifiers)
9. [Interpreter Reference Algorithm](#9-interpreter-reference-algorithm)
10. [Grammar (Formal, EBNF)](#10-grammar-formal-ebnf)
11. [Storage Model](#11-storage-model)
12. [Worked Examples](#12-worked-examples)
13. [Compliance and Conformance](#13-compliance-and-conformance)
14. [Versioning](#14-versioning)
15. [Glossary](#15-glossary)

---

## 1. Overview and Design Principles

### 1.1 What the language is

This is a compact, text-based, imperative drawing language. A program in this language is a sequence of **opcodes** that move an imaginary pen across a two-dimensional plane, leaving marks (lines, shapes, text) according to well-defined rules.

Every visible mark on any drawing — every line, symbol, arc, curve, character of text, and later raster image — is produced by executing a program in this language. There is no other way to place marks on a drawing. There are no hidden primitives, no framework-injected geometry, and no output-format-specific escape hatches.

### 1.2 Design principles (non-negotiable)

The language is designed around six principles. Every proposed extension must be evaluated against them.

1. **Minimalism.** The language has the smallest possible set of opcodes that still expresses every drawing operation the editor must support. Two categories exist: the **Core** (frozen) and the **Extensions** (additive). No new syntax forms are ever introduced — extensions must reuse the existing lexical shape.
2. **Compositionality.** Complex drawings are built from simple opcodes composed in sequence. There are no compound statements, blocks, subroutines, conditionals, or variables. A program is a flat list of opcodes.
3. **Determinism.** Given the same program and starting pen state, the interpreter always produces the same output. No random effects, no time-dependent behavior, no floating-point tolerance issues visible at the language level.
4. **Storage as the source of truth.** Programs are stored as rows in a database. The interpreter reads programs from the database and produces output. The database is authoritative; the rendered output is derived, disposable, and reproducible.
5. **Output-format neutrality.** The language does not know about SVG, PostScript, PDF, or any other output format. The interpreter emits abstract drawing calls that are then translated by a backend into the target format. The same program produces identical drawings in every backend, up to the resolution of the backend.
6. **Human-writable and human-readable.** A skilled user can read and write the language directly. Programs are ASCII text, use short mnemonic opcodes, and follow a consistent grammar. This is deliberate — the editor stores programs as text, not as compiled binary.

### 1.3 What the language is *not*

- It is not a general-purpose programming language. It has no variables, no arithmetic, no control flow, no functions.
- It is not a page description language like PostScript or PDF. Those are output formats produced *from* this language.
- It is not a markup language like SVG or HTML. Those are output formats produced *from* this language.
- It is not extensible by users at runtime. New opcodes can only be added by revising this specification and updating the interpreter.

### 1.4 Two categories of opcodes

- **Core opcodes (Section 6).** Seven opcodes. Frozen forever. Every compliant interpreter must implement all seven exactly as specified.
- **Extension opcodes (Section 7).** Four opcodes. Additive. Compliant interpreters SHOULD implement them; a program is valid if it uses only Core opcodes, or Core + any subset of Extensions.

---

## 2. Notation Used in This Document

Throughout the specification:

- `MONOSPACE` denotes literal text of the language.
- *italics* denote placeholders — you substitute a concrete value.
- **Bold** denotes semantic keywords or emphasis.
- `⟨…⟩` denotes a syntactic category that is defined elsewhere in the grammar.
- `[…]` denotes an optional element.
- `(…)*` denotes zero-or-more repetition.
- `(…)+` denotes one-or-more repetition.
- **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY** follow RFC 2119 semantics.

Numeric values in examples are exact. When an argument is a signed integer, negative values are explicitly written with a leading `-` (for example, `-14`). When an argument is a floating-point number, a decimal point is always present, even for whole values (for example, `0.` or `90.0`). This convention is enforced by the grammar and disambiguates numeric types without a type prefix.

---

## 3. Lexical Structure

### 3.1 Character set

Programs are ASCII text. Byte values `0x20` (space) through `0x7E` (tilde) are permitted. Line terminators (`\n`, `\r\n`) are permitted but not significant — they are treated identically to space. Tab characters (`\t`) are permitted and treated as space.

### 3.2 Program structure

A **program** is a sequence of zero or more **statements**, each terminated by a semicolon (`;`).

```
program        ::= ( statement ";" )*
statement      ::= opcode ( "," argument )*
opcode         ::= two-letter-mnemonic
argument       ::= number | string | modifier
```

Whitespace between tokens is optional and ignored. The following are equivalent programs:

```
mr,0,158;dl,14,0;
mr, 0, 158; dl, 14, 0;
mr,0,158 ; dl,14,0 ;
```

### 3.3 Opcodes

An opcode is a two-letter lowercase ASCII mnemonic. The complete set is defined in Sections 6 and 7. Any two-letter sequence not listed in those sections is a **lexical error** — a compliant interpreter MUST reject the program and MUST NOT attempt to guess the meaning.

### 3.4 Arguments

Arguments are comma-separated. Each opcode declares its required argument count and types (Sections 6 and 7). Passing the wrong number or wrong type of arguments is a **semantic error** — the interpreter MUST reject the program.

Three argument types exist:

- **Integer.** A signed decimal integer. Grammar: `-?[0-9]+`. Example: `14`, `-158`, `0`.
- **Numeric literal grace clause (v0.3).** No opcode argument is declared as Float. Where a numeric argument is written with a decimal point (e.g. `0.`, `90.`, `3.14`, `-.5`), the interpreter MUST parse it as a real number and then round it to the nearest int using round-half-toward-positive-infinity:

  | Written | Stored |
  |---|---|
  | `0.` | `0` |
  | `90.` | `90` |
  | `3.14` | `3` |
  | `3.5` | `4` |
  | `-3.5` | `-3` |
  | `-3.6` | `-4` |
  | `89.5` | `90` |
  | `89.499` | `89` |

  Rule in one line: `stored = floor(written + 0.5)`. This is the classical school-math rule (half rounds *up* toward positive infinity), not Python's `round()` (which rounds half-to-even). It preserves compatibility with the ~3,610 `tx,90.` values in the real legacy backup and any hand-written v0.1/v0.2 template, while keeping the runtime type system to a single integer type.

  Emitters generating new programs SHOULD write the canonical integer form (`tx,0,`) rather than `tx,0.`.

  A literal that is neither an Integer nor a decimal-point number (letters, garbage) is a **semantic error** — the interpreter MUST reject the program.
- **String.** A sequence of characters. Strings do not use delimiters — the string argument runs from the comma that precedes it to the semicolon that terminates the statement. This means strings MUST NOT contain the semicolon character. See §6.7 for details.
- **Modifier.** A single letter (or letter-plus-digit combination), preceded by a comma. Modifiers appear at the end of a statement, after all positional arguments. See §8.

### 3.5 Comments

A `#` character starts a **line comment** that continues to (but does not include) the next line terminator (`\n`). Comments are stripped from the input before any other lexical processing; they carry no semantic meaning and never affect statement count, argument values, or pen state.

Comments MAY appear:

- On their own line, before, after, or between statements.
- At the end of a line, after a terminating `;`.

Comments MUST NOT appear inside a statement (between an opcode and its terminating `;`) except inside a `tx` string argument. Inside a `tx` string argument, `#` is literal text: because a `tx` string extends from the comma that precedes it to the terminating `;` (§3.4, §6.7), and comments are line-scoped, a `#` inside such a string can only ever be part of the string.

Example:

```
# Frame template — outer border of an A4 sheet
ma,10,10;      # top-left corner
dl,780,0;      # top edge
tx,12.,Item #4 quantity;   # the '#' inside the tx string is literal
```

Compliant interpreters MUST strip comments before tokenization. A compliant program MAY contain no comments at all — comments are an authoring affordance, not a required feature.

Documentation about a program that lives *outside* the program — for example, in a `description` column adjacent to the `cmd` column of a database row — remains the recommended place for structured metadata (author, revision, provenance). Line comments are for inline authoring notes that belong logically inside the program text.

### 3.6 Case sensitivity

Opcodes are lowercase. Modifiers are lowercase. String arguments preserve case as authored. Any uppercase opcode or modifier is a lexical error.

---

## 4. Coordinate System and Units

### 4.1 Origin and axes

The coordinate system is a Cartesian plane.

- The origin `(0, 0)` is the **lower-left corner** of the drawing area.
- The **X axis** points **right**. Positive X = rightward.
- The **Y axis** points **up**. Positive Y = upward.

This is the mathematical convention (y-up), matching PostScript and PDF. When an output backend needs a y-down coordinate system (SVG, screen pixels, most raster libraries), the backend performs the flip. The language and the stored programs are always y-up.

### 4.2 Units

All coordinates and lengths are in **abstract drawing units**. The language does not fix the physical meaning of one unit. A drawing sheet declares its unit-to-millimeter ratio in its own database row (in the `frame` table). The interpreter operates purely in abstract units; the backend converts to the physical output medium.

Angles are always in **degrees**. Positive angle = counterclockwise rotation. Zero degrees = pointing right along the +X axis.

### 4.3 Numeric ranges

- Integer coordinates and lengths are 16-bit signed integers by default: −32,768 to 32,767.
- Floats are IEEE 754 double-precision. Practical range for angles and small dimensions is far smaller; the double type is used only to keep intermediate computation exact.

Overflow (integer argument outside the 16-bit range) is a semantic error unless a specific opcode documents a wider range.

---

## 5. Pen State Model

### 5.1 The pen

The interpreter maintains a single **pen** with the following state:

| Property | Type | Initial value | Modified by |
|---|---|---|---|
| position | (x, y) integer pair | (0, 0) | Every opcode that draws or moves |
| text size | integer | 10 | `tz` |
| pen down flag | boolean | false | Implicit; see §5.2 |

There is exactly one pen. There is no pen stack, no save/restore, no multiple pens. All state is global and mutable in-sequence.

### 5.2 Pen-up and pen-down semantics

The pen is conceptually "up" (not touching the surface) between statements. It is "down" only during the execution of a drawing opcode (`dl`, `rt`, `ci`, `ar`, `bz`, `sp`, `tx`, `im`). After a drawing opcode finishes, the pen returns to "up" and stays at the endpoint of the last stroke.

This means:

- **Move opcodes** (`mr`, `ma`) never draw. They only reposition the pen.
- **Draw opcodes** (`dl`, `rt`, `ci`, `ar`, `bz`, `sp`, `tx`, `im`) draw a shape starting at the current pen position, then update the pen position to the endpoint of that shape.

The pen position after each opcode is defined precisely in the opcode's specification (Sections 6 and 7).

### 5.3 State persistence

Pen state persists across statements within a single program execution. When execution begins, state is initialized to the values in §5.1. When execution ends, state is discarded.

Programs are independent. Executing program B after program A does not inherit any pen state from A.

---

## 6. Core Opcodes (Basics)

Seven opcodes. Frozen forever. Every compliant interpreter MUST implement all seven exactly as specified below.

### 6.1 `mr` — move relative

**Syntax:** `mr,dx,dy`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | dx | integer | Displacement along X. Positive = right. |
| 2 | dy | integer | Displacement along Y. Positive = up. |

**Semantics:** Sets pen position to `(current_x + dx, current_y + dy)`. Does not draw.

**Pen position after:** `(current_x + dx, current_y + dy)`.

**Example:**
```
mr,10,20;
```
If pen was at `(100, 100)`, it is now at `(110, 120)`.

---

### 6.2 `ma` — move absolute

**Syntax:** `ma,x,y`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | x | integer | Absolute X coordinate. |
| 2 | y | integer | Absolute Y coordinate. |

**Semantics:** Sets pen position to `(x, y)`. Does not draw.

**Pen position after:** `(x, y)`.

**Example:**
```
ma,500,300;
```
Pen is now at `(500, 300)` regardless of prior position.

---

### 6.3 `dl` — draw line (relative)

**Syntax:** `dl,dx,dy[,i]`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | dx | integer | Displacement along X to the endpoint. |
| 2 | dy | integer | Displacement along Y to the endpoint. |

**Modifiers accepted:** `,i` (invisible), `,d` (dashed), `,c<n>` (color). See §8.

**Semantics:** Draws a straight line from the current pen position to `(current_x + dx, current_y + dy)`. Line width is defined by the backend's default stroke width (typically 1 unit); backends MAY offer configuration, but the language does not carry stroke width. When `,i` (v0.4) is present, the line contributes both endpoints to the bounding-box accumulator but is not rendered — used to reserve extent in symbol definitions without drawing a visible mark, exactly like `,i` on `rt`. The pen still advances to the endpoint.

**Pen position after:** `(current_x + dx, current_y + dy)`.

**Example:**
```
ma,0,0; dl,100,0; dl,0,50;
```
Draws an L-shape: right 100 units, then up 50 units.

**Example with invisible modifier (v0.4):**
```
ma,-12,-12; rt,24,25,i; dl,10,0,i; mr,-10,0; dl,0,10,i;
```
Reserves a 24×25 bounding box then walks an invisible L-path to extend the extent; nothing renders but the drawing's bounding box now includes those endpoints. Pattern taken from real legacy pic_ex 24904.

---

### 6.4 `rt` — rectangle

**Syntax:** `rt,w,h[,f][,i]`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | w | integer | Width. May be negative (extends leftward). |
| 2 | h | integer | Height. May be negative (extends downward). |

**Modifiers accepted:** `,f` (fill), `,i` (invisible / atmend boundary). See §8.

**Semantics:** Draws an axis-aligned rectangle with one corner at the current pen position and the opposite corner at `(current_x + w, current_y + h)`. When `,f` is present, the rectangle is filled with the current stroke color; when absent, only the outline is stroked. When `,i` is present, the rectangle contributes to bounding-box calculation but is not rendered — used to define invisible boundary segments in **atmende** (breathing/expandable) blocks. `,i` and `,f` MAY appear together in either order.

**Pen position after:** Unchanged. The pen returns to its position before the `rt` statement.

**Example:**
```
ma,10,10; rt,80,40;
```
Draws an 80×40 outline rectangle with lower-left corner at (10, 10).

```
ma,10,10; rt,80,40,f;
```
Draws the same rectangle, filled.

---

### 6.5 `ci` — circle

**Syntax:** `ci,r[,f]`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | r | integer | Radius. Must be positive. |

**Modifiers accepted:** `,f` (fill). See §8.

**Semantics:** Draws a full 360° circle centered at the current pen position, with radius `r`. When `,f` is present, the disk is filled; when absent, only the outline is stroked.

**Pen position after:** Unchanged.

**Example:**
```
ma,100,100; ci,20;
```
Draws an outline circle of radius 20 centered at (100, 100).

```
ma,100,100; ci,3,f;
```
Draws a filled dot of radius 3 at (100, 100).

---

### 6.6 `tz` — set text size

**Syntax:** `tz,size`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | size | integer | Text size in abstract units. Must be positive. |

**Semantics:** Sets the pen's text size property to `size`. Affects all subsequent `tx` operations until another `tz` is executed. Does not draw.

**Pen position after:** Unchanged.

**Example:**
```
tz,12;
```
Text drawn by subsequent `tx` operations will be 12 units tall.

---

### 6.7 `tx` — draw text

**Syntax:** `tx,angle,string`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | angle | int | Rotation in degrees, counterclockwise. `0` = horizontal, reading left-to-right. `90` = rotated 90° CCW (reading bottom-to-top). Whole degrees. Decimal-point literals are accepted and rounded per §3.4. |
| 2 | string | string | The characters to render. Runs from the comma that separates it from `angle`, up to but not including the terminating semicolon. Escaping is not defined; the string MUST NOT contain a semicolon. |

**Semantics:** Draws the string starting at the current pen position, in the current text size (set by the most recent `tz`), rotated by `angle` degrees around the current pen position. The text baseline aligns with the pen position; the first character extends to the right of the pen position (in unrotated space) and upward for accents.

**Font:** The language does not specify a font. The backend chooses a monospaced or proportional font appropriate to the output medium. Editors MAY expose font selection at the drawing level (a separate database column on the `obj_f` or `frame` row), but the cmd string itself does not carry font information.

**Pen position after:** Unchanged. The pen does not advance across the string.

**Examples:**
```
ma,50,50; tz,14; tx,0.,Hello World;
```
Draws "Hello World" horizontally at (50, 50), height 14.

```
ma,50,50; tz,10; tx,90.,BM Global;
```
Draws "BM Global" rotated 90° CCW (reads from bottom to top) at (50, 50).

---

## 7. Extension Opcodes

Four opcodes. Additive. Extensions preserve all invariants of the Core: same lexical shape, same modifier system, same coordinate model, same pen model. Compliant interpreters SHOULD implement extensions; programs using only Core opcodes remain valid.

### 7.1 `ar` — arc

**Syntax:** `ar,r,start_angle,sweep_angle[,f]`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | r | integer | Radius. Must be positive. |
| 2 | start_angle | int | Angle at which the arc begins, in degrees. `0` = pointing right along +X. Whole degrees. Decimal-point literals are accepted and rounded per §3.4. |
| 3 | sweep_angle | int | Arc extent, in degrees. Positive = counterclockwise, negative = clockwise. A sweep of `360` (or `-360`) yields a full circle, semantically identical to `ci,r`. Whole degrees. Decimal-point literals are accepted and rounded per §3.4. |

**Modifiers accepted:** `,f` (fill the pie slice — the region bounded by the two radii and the arc).

**Semantics:** Draws a circular arc of radius `r` centered at the current pen position, beginning at angle `start_angle` and sweeping by `sweep_angle`. When `,f` is present, the closed pie-slice region (arc plus the two straight radii from the center to the arc endpoints) is filled.

**Pen position after:** Unchanged. The center is still the pen position. This is deliberate: arcs frequently appear in sequences where multiple arcs share a center.

**Rationale:** `ar` is a strict superset of `ci`. `ci,r` is exactly equivalent to `ar,r,0.,360.`. `ci` is retained in the language for concision and because existing pictogram data uses it.

**Examples:**
```
ma,100,100; ar,50,0.,90.;
```
Draws a quarter-arc (top-right quadrant) of radius 50 centered at (100, 100).

```
ma,100,100; ar,50,180.,180.;
```
Draws a half-arc (upper half) of radius 50 centered at (100, 100).

```
ma,100,100; ar,50,45.,-90.,f;
```
Draws a filled pie slice from 45° sweeping clockwise 90° (ending at −45°).

---

### 7.2 `bz` — cubic Bézier curve

**Syntax:** `bz,dx1,dy1,dx2,dy2,dx3,dy3`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1–2 | dx1, dy1 | integer | First control point, relative to current pen position. |
| 3–4 | dx2, dy2 | integer | Second control point, relative to current pen position. |
| 5–6 | dx3, dy3 | integer | Endpoint, relative to current pen position. |

**Modifiers accepted:** None in this version. `,f` is not permitted on `bz` because a single Bézier segment is not a closed path.

**Semantics:** Draws a cubic Bézier curve from the current pen position `P0 = (x, y)` to `P3 = (x + dx3, y + dy3)`, with control points `P1 = (x + dx1, y + dy1)` and `P2 = (x + dx2, y + dy2)`. Standard cubic-Bézier interpolation:

`B(t) = (1−t)³ P0 + 3(1−t)² t P1 + 3(1−t) t² P2 + t³ P3`, for t ∈ [0, 1].

**Pen position after:** `(x + dx3, y + dy3)`. This matches `dl` — the pen advances to the endpoint. This lets `bz` compose naturally with `dl` in a mixed straight/curved path.

**Rationale:** Cubic Bézier is the industry-standard curve primitive (PostScript `curveto`, SVG `C`, PDF `c`). One primitive covers arcs (approximated), splines, and free-form curves. Three control points (six numbers) is the minimum expressive form.

**Example:**
```
ma,0,0; bz,50,100,150,100,200,0;
```
Draws an S-curve from (0, 0) to (200, 0), bulging up at x ≈ 50 and dipping toward x ≈ 150.

---

### 7.3 `sp` — spline (polyline through anchor points)

**Syntax:** `sp,x1,y1,x2,y2,…,xN,yN`

**Arguments:** A sequence of `2N` integers representing `N` anchor points in absolute coordinates, where `N ≥ 2`. The first anchor is the start; the last is the end.

**Modifiers accepted:** `,f` (fill the closed region bounded by the spline and the straight segment from the last anchor back to the first — used when authoring closed curved shapes).

**Semantics:** Draws a smooth curve that passes through every anchor point in order. The curve is computed as a **Catmull-Rom spline** with tension = 0.5, which is then converted to a chain of cubic Béziers for rendering. Interpreters MUST use this exact conversion so that all backends produce identical output.

**Catmull-Rom to Bézier conversion** (reference algorithm, tension = 0.5):

For each pair of consecutive anchor points `Pi, Pi+1`, with neighbors `Pi−1` and `Pi+2`:
- Control point 1 = `Pi + (Pi+1 − Pi−1) / 6`
- Control point 2 = `Pi+1 − (Pi+2 − Pi) / 6`

Endpoint handling: for the first segment, treat `P−1 = P0`; for the last segment, treat `PN+1 = PN`.

**Pen position after:** `(xN, yN)` — the last anchor point.

**Rationale:** `sp` is an authoring convenience over `bz`. The editor stores the anchor points the user drew; the interpreter expands them to Béziers on the fly. This means the user can drag an anchor and the curve reshapes coherently — an operation that would be far harder to expose in raw `bz` form.

**Example:**
```
sp,0,0,50,100,150,100,200,0;
```
Draws a smooth curve passing through (0, 0), (50, 100), (150, 100), (200, 0).

**Interpreter guidance:** Interpreters MAY internally expand `sp` to a series of `bz` calls at parse time or at render time — the choice is invisible outside the interpreter.

---

### 7.4 `im` — raster image placement

**Syntax:** `im,w,h,image_id`

**Arguments:**

| # | Name | Type | Meaning |
|---|---|---|---|
| 1 | w | integer | Display width in drawing units. |
| 2 | h | integer | Display height in drawing units. |
| 3 | image_id | integer | Foreign key into a separate `img` table that stores the raster bytes. |

**Modifiers accepted:** None in this version.

**Semantics:** Places a raster image at the current pen position, occupying a box of width `w` and height `h`. The image occupies the rectangle with lower-left corner at the current pen position and upper-right at `(x + w, y + h)`. The image content is looked up by `image_id` in the `img` table (schema defined separately from this specification, but conceptually holding `image_id`, `mime_type`, `bytes`).

**Pen position after:** Unchanged.

**Rationale:** Raster images (photos, scanned diagrams, logos) do not fit the vector model of the language, but their placement does. `im` treats a raster as a black-box "stamp" with a size and an identity; the actual pixel data lives outside the cmd string. Nothing else in the drawing model needs to change to accommodate images.

**Example:**
```
ma,500,400; im,120,80,42;
```
Places image with `image_id = 42` at (500, 400), sized 120×80 units.

---

## 8. Modifiers

Modifiers are single-letter suffixes (optionally followed by digits) that modify the behavior of the preceding opcode. They MUST appear after all positional arguments and before the terminating semicolon.

### 8.1 Defined modifiers

| Modifier | Meaning | Applies to | Notes |
|---|---|---|---|
| `,f` | Fill | `rt`, `ci`, `ar`, `sp` | Fills the closed shape with the current stroke color. Not applicable to open paths (`dl`, `bz`). |
| `,i` | Invisible / atmend boundary | `rt`, `dl` (v0.4) | Marks the geometry as contributing to bounding-box computation but not rendered. Used to define expandable-block boundaries and to reserve symbol extent without visible strokes. For `dl`, the pen still advances to the endpoint. |
| `,d` | Dashed stroke | `dl`, `rt`, `ci`, `ar`, `bz`, `sp` | Renders the stroke as a dashed line. The dash pattern is defined by the backend (typically 4-on-4-off in drawing units). |
| `,c`*n* | Color palette index | Any drawing opcode | Selects color number *n* from the drawing's palette table. `n` is a non-negative integer written immediately after `c`, e.g. `,c0`, `,c1`, `,c15`. The mapping from `n` to an RGB value is stored in a separate `palette` table, not in the cmd string. Palette index 0 is always "default stroke color" (typically black). |

### 8.2 Combining modifiers

Multiple modifiers MAY appear on the same statement, separated by commas, in any order. Example:

```
rt,80,40,f,c2;
```

Renders an 80×40 filled rectangle in palette color 2.

```
dl,100,0,d,c1;
```

Renders a dashed line 100 units long in palette color 1.

### 8.3 Interpreter handling of unknown modifiers

An unknown modifier is a lexical error. The interpreter MUST reject the program. This preserves the closed-set property of the language and prevents silent misinterpretation of typos.

---

## 9. Interpreter Reference Algorithm

The following is a reference implementation, expressed in language-neutral pseudocode. Any compliant interpreter MUST behave identically to this reference for every well-formed program.

```
function interpret(program_text, backend):
    pen = PenState(x=0, y=0, text_size=10)
    tokens = tokenize(program_text)
    for statement in split_statements(tokens):
        opcode = statement.opcode
        args = statement.args
        modifiers = statement.modifiers

        switch opcode:
            case "mr":
                validate(args, [int, int]); no_modifiers(modifiers)
                pen.x += args[0]
                pen.y += args[1]

            case "ma":
                validate(args, [int, int]); no_modifiers(modifiers)
                pen.x = args[0]
                pen.y = args[1]

            case "dl":
                validate(args, [int, int]); allow_modifiers(modifiers, {"d", "c"})
                x1, y1 = pen.x, pen.y
                x2, y2 = pen.x + args[0], pen.y + args[1]
                backend.draw_line(x1, y1, x2, y2, modifiers)
                pen.x, pen.y = x2, y2

            case "rt":
                validate(args, [int, int]); allow_modifiers(modifiers, {"f", "i", "d", "c"})
                backend.draw_rectangle(pen.x, pen.y, args[0], args[1], modifiers)
                # pen unchanged

            case "ci":
                validate(args, [int]); allow_modifiers(modifiers, {"f", "d", "c"})
                backend.draw_circle(pen.x, pen.y, args[0], modifiers)
                # pen unchanged

            case "tz":
                validate(args, [int]); no_modifiers(modifiers)
                pen.text_size = args[0]

            case "tx":
                validate(args, [float, string]); allow_modifiers(modifiers, {"c"})
                backend.draw_text(pen.x, pen.y, pen.text_size, args[0], args[1], modifiers)
                # pen unchanged

            # Extensions

            case "ar":
                validate(args, [int, float, float]); allow_modifiers(modifiers, {"f", "d", "c"})
                backend.draw_arc(pen.x, pen.y, args[0], args[1], args[2], modifiers)
                # pen unchanged

            case "bz":
                validate(args, [int, int, int, int, int, int]); allow_modifiers(modifiers, {"d", "c"})
                p0 = (pen.x, pen.y)
                p1 = (pen.x + args[0], pen.y + args[1])
                p2 = (pen.x + args[2], pen.y + args[3])
                p3 = (pen.x + args[4], pen.y + args[5])
                backend.draw_bezier(p0, p1, p2, p3, modifiers)
                pen.x, pen.y = p3

            case "sp":
                validate(args_count_even_and_at_least(4)); allow_modifiers(modifiers, {"f", "d", "c"})
                anchors = pair_up(args)
                beziers = catmull_rom_to_bezier(anchors, tension=0.5)
                for (p0, p1, p2, p3) in beziers:
                    backend.draw_bezier(p0, p1, p2, p3, modifiers)
                pen.x, pen.y = anchors[-1]

            case "im":
                validate(args, [int, int, int]); no_modifiers(modifiers)
                backend.place_image(pen.x, pen.y, args[0], args[1], image_id=args[2])
                # pen unchanged

            default:
                raise LexicalError("unknown opcode: " + opcode)

    return backend.finalize()
```

The `backend` object is an interface with methods `draw_line`, `draw_rectangle`, `draw_circle`, `draw_text`, `draw_arc`, `draw_bezier`, `place_image`, and `finalize`. Concrete backends (SVG, PostScript) implement these methods; the interpreter itself is backend-agnostic.

---

## 10. Grammar (Formal, EBNF)

```
program        = { statement } ;
statement      = opcode , { "," , argument } , { "," , modifier } , ";" ;

opcode         = core_opcode | extension_opcode ;
core_opcode    = "mr" | "ma" | "dl" | "rt" | "ci" | "tz" | "tx" ;
extension_opcode = "ar" | "bz" | "sp" | "im" ;

argument       = integer | number-with-decimal-point | string ;
                 (* number-with-decimal-point is a v0.3 grace form:
                    the interpreter rounds it half-toward-positive-infinity
                    to an integer at parse time. See §3.4. *)
integer        = [ "-" ] , digit , { digit } ;
float          = [ "-" ] , ( digit , { digit } , "." , { digit }
                           | "." , digit , { digit } ) ;
string         = { any_character_except_semicolon } ;

modifier       = "f" | "i" | "d" | color_modifier ;
color_modifier = "c" , digit , { digit } ;

digit          = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" ;
any_character_except_semicolon = any_printable_ASCII − ";" ;
```

Whitespace (space, tab, newline, carriage return) is permitted between any two tokens and is not part of the grammar. Tokens are the opcode, each argument, each modifier, and the terminating semicolon.

---

## 11. Storage Model

Programs are stored in database columns of type "variable-character up to 256 bytes" (or the equivalent in the target database). A single row typically holds one program, which is a single drawing element (a pictogram, a frame element, a text label, a placed symbol).

### 11.1 Tables that hold cmd strings

| Table | Column | Purpose |
|---|---|---|
| `pic_b` | `cmd` | Pictogram definition (a reusable symbol). |
| `pic_ex` | `cmd` | Extended pictogram — used when a symbol renders differently in the palette vs. on the drawing. Also used for **frame elements**: paper border, grid lines, corner marks, title-block outline. |
| `pic_d` | (parameters) | Title-block field data (labels and coordinates for the fields inside the frame's Schriftfeld). |
| `obj_g` | (references + placement) | An instance of a pictogram placed on a drawing at a specific position, angle, and mirror state. |
| `konnektor` | (endpoints) | A connection (wire) between two pictogram instances. Rendered as a sequence of `dl` operations by the interpreter's wiring subsystem. |
| `schr_d` | `cmd` | Free-standing text label. |

The schema for these tables is defined elsewhere in the project and is out of scope for this language specification. What matters here is: **every visible mark on a drawing traces back to a cmd string in one of these tables.** Nothing is drawn by code.

### 11.2 Program length

A single cmd string is up to 256 characters. When a drawing element is complex enough to exceed this (typical for pictograms with many strokes), multiple rows are used, distinguished by a sequence number (`lau` in the existing schema). The interpreter concatenates rows in order of `lau` before executing.

---

## 12. Worked Examples

### 12.1 A rectangle with a diagonal line

```
ma,10,10; rt,80,40; dl,80,40;
```

Draws an 80×40 outline rectangle at (10, 10), then a diagonal line from the current pen position (which is unchanged after `rt`, so still (10, 10)) to (90, 50).

### 12.2 A crosshair mark

```
ma,100,100; mr,-10,0; dl,20,0; mr,-10,-10; dl,0,20;
```

Moves to (100, 100), then draws a 20-unit horizontal line centered on (100, 100), then a 20-unit vertical line centered on (100, 100).

### 12.3 A filled bullet with text label

```
ma,50,50; ci,3,f; mr,8,-4; tz,10; tx,0.,Bohemia Market;
```

Places a filled dot of radius 3 at (50, 50), moves right and slightly down, sets text size to 10, and draws the label "Bohemia Market" horizontally.

### 12.4 A quarter-circle icon

```
ma,100,100; ar,20,90.,90.;
```

Draws a quarter-arc, radius 20, centered at (100, 100), starting at 90° (straight up) and sweeping 90° counterclockwise (ending at 180°, straight left).

### 12.5 A smooth curve through four points

```
sp,0,0,30,50,80,50,120,0;
```

Draws a smooth Catmull-Rom curve passing through (0, 0), (30, 50), (80, 50), and (120, 0).

### 12.6 A block with a photo inset

```
ma,10,10; rt,200,150; ma,20,20; im,180,100,7; ma,20,130; tz,12; tx,0.,PID Section A;
```

Draws a 200×150 frame at (10, 10), places image #7 sized 180×100 inside it, and adds a caption at the top.

### 12.7 A dashed reference line

```
ma,0,50; dl,300,0,d;
```

Draws a dashed horizontal reference line from (0, 50) to (300, 50).

### 12.8 An expandable-block boundary (atmend)

```
ma,0,0; rt,100,50,i; ma,10,10; tx,0.,Content;
```

Declares an invisible bounding rectangle of 100×50 (contributes to the block's expandable footprint but is not drawn), then places the label "Content" inside it.

---

## 13. Compliance and Conformance

### 13.1 A conforming interpreter

An implementation is a **conforming interpreter** of this specification if and only if:

1. It accepts every well-formed program (per §10 grammar) and rejects every ill-formed program.
2. It implements all seven Core opcodes exactly as specified in §6.
3. It handles all defined modifiers exactly as specified in §8.
4. It produces output identical to the reference algorithm in §9, up to the resolution of the chosen backend.
5. It rejects unknown opcodes and unknown modifiers as errors.
6. It implements each Extension opcode either fully (per §7) or not at all — partial extension support is not conforming.

### 13.2 A conforming program

A program is **conforming** if:

1. It parses under the grammar in §10.
2. Every opcode is either a Core opcode or an implemented Extension.
3. Every modifier is defined for its opcode.
4. Every numeric argument is within its declared range.

### 13.3 Interoperability

Two conforming interpreters, given the same conforming program, MUST produce visually equivalent output. "Visually equivalent" means: every mark appears at the same position within one drawing unit; every closed shape has the same fill state; every text string is rendered with the same content, rotation, and size (the exact font may vary between backends).

---

## 14. Versioning

This specification is versioned. Version numbers follow **major.minor** semantics.

- **Major version** increments when a change is made that breaks conformance of previously-conforming programs or interpreters. Examples: removing an opcode, changing the meaning of an existing opcode, changing the coordinate system.
- **Minor version** increments when a change is additive: new Extension opcodes, new modifiers, clarifications, examples.

Current version: **0.4 (locked, 2026-08-09)**. Approved by the project owner as the frozen reference. All interpreters and programs are built against this version.

**Version history:**

- **0.4 (2026-08-09).** `dl` opcode accepts the `i` (invisible) modifier. Semantics: pen still advances, both endpoints contribute to the bounding-box accumulator, but no visible mark is emitted. Additive; every v0.3 program is a valid v0.4 program. Motivated by real legacy pic_ex programs (≈10% of the imported library) that use invisible line moves to reserve symbol extent without visible strokes.
- **0.3 (2026-08-09).** FLOAT type removed; the language has one numeric type, INT (signed 16-bit). `tx` and `ar` argument declarations changed from FLOAT to INT. Decimal-point literals are accepted and rounded half-toward-positive-infinity to the nearest integer (§3.4 grace clause). Backward-compatible with every real legacy program and every v0.1/v0.2 program that used only whole-degree angles.
- **0.2 (2026-08-09).** Added line-comment syntax to §3.5. Additive; every v0.1 program is a valid v0.2 program.
- **0.1 (2026-08-09).** Initial locked release. Seven Core opcodes, four Extension opcodes, four modifiers. No comments.

Interpreters SHOULD document which version of the specification they implement. Programs MAY declare a required minimum version as an out-of-band annotation (in a database column adjacent to the cmd column); the cmd string itself does not carry a version marker.

---

## 15. Glossary

- **Anchor point.** A point that a spline (`sp`) passes through exactly.
- **Atmend / atmende block.** A "breathing" or expandable block whose bounding rectangle is defined by an invisible (`,i`) `rt` and whose contents can grow within that bound.
- **Backend.** A concrete output-format module (SVG, PostScript, PDF) that receives abstract drawing calls from the interpreter and emits the target format.
- **cmd string.** The text of a program, as stored in a database column.
- **Compliant / conforming.** Following this specification exactly.
- **Control point.** A point used by a Bézier curve to shape the curve but which the curve does not necessarily pass through.
- **Core opcode.** One of the seven original opcodes: `mr`, `ma`, `dl`, `rt`, `ci`, `tz`, `tx`.
- **Extension opcode.** One of the additional opcodes: `ar`, `bz`, `sp`, `im`.
- **Interpreter.** A software component that reads a cmd string and produces drawing output.
- **Konnektor.** A connection (wire) between two placed pictograms; rendered as a sequence of `dl` operations.
- **Modifier.** A single-letter (or letter-plus-digit) suffix on a statement that alters its behavior: `,f`, `,i`, `,d`, `,c`*n*.
- **Opcode.** A two-letter mnemonic identifying a drawing operation.
- **Pen.** The abstract cursor whose state (position, text size) the interpreter maintains.
- **Pictogram.** A reusable graphical symbol, defined by one or more `pic_b` rows and placed by `obj_g` rows.
- **Program.** A sequence of statements — that is, a cmd string.
- **Rahmen.** The frame/border of a drawing sheet.
- **Raster.** The grid of reference labels (A/B/C/D/E/F rows and 1/2/…/8 columns) along the border of a frame.
- **Schriftfeld.** The title block on a drawing sheet, containing metadata (project, drawing number, revision, etc.).
- **Statement.** One opcode plus its arguments and modifiers, terminated by a semicolon.

---

**End of specification.**
