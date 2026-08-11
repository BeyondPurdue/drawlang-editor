# Step 3 — Canvases: DB schema + read-only API

## Purpose

Everything the canvas editor (Step 6) draws must go through a single API:
`POST /api/canvases/{id}/statements`. Before that API can exist (Step 4), the
database must store a **canvas** and, per canvas, a **statement sequence** —
one row per drawlang statement, in program order.

Step 3 delivers the schema + the read-only API. Writes come in Step 4.

## Design principle

The database is the single source of truth. Rendering is a pure function of
the statements read from the database. The rendered SVG/PDF is disposable and
reproducible.

## Schema

Two new tables. The existing `drawings` table is untouched — it keeps working
as a legacy "whole-program blob" store; new work uses `canvases`.

```
CREATE TABLE canvases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,     -- URL-friendly id
    name         TEXT    NOT NULL,            -- human title
    frame_id     TEXT,                        -- optional frame template (e.g. 'a3-grid')
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);

CREATE INDEX idx_canvases_slug ON canvases(slug);
CREATE INDEX idx_canvases_updated_at ON canvases(updated_at DESC);

CREATE TABLE statements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    canvas_id    INTEGER NOT NULL,
    seq          INTEGER NOT NULL,            -- 0-based order in the program
    opcode       TEXT    NOT NULL,            -- e.g. 'mr', 'dl', 'tx'
    args         TEXT    NOT NULL,            -- serialized: 'x,y' or '0,BM Global'
    group_id     TEXT,                        -- optional group tag (comment-fence marker)
    created_at   REAL    NOT NULL,
    FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE
);

CREATE INDEX idx_statements_canvas ON statements(canvas_id, seq);
CREATE INDEX idx_statements_group ON statements(canvas_id, group_id);
```

## Statement serialization

`opcode` and `args` are stored separately so the DB is the language, not a
blob of text:
- `mr,14,0;` → `opcode='mr', args='14,0'`
- `tx,0,BM Global A.S.;` → `opcode='tx', args='0,BM Global A.S.'`
- Comment lines are NOT stored — they exist only in `.drawlang` files.

Reconstructing a program from statements: join in `seq` order as
`f"{opcode},{args};\n"`. This is exactly what the interpreter parses.

## Read-only API (Step 3 delivers this)

### `GET /api/canvases`
List all canvases. Response:
```json
{
  "canvases": [
    {"id": 1, "slug": "my-drawing", "name": "My drawing",
     "frame_id": "a3-grid", "statement_count": 469,
     "created_at": 1723372800.0, "updated_at": 1723372800.0}
  ]
}
```

### `GET /api/canvases/{id_or_slug}`
Fetch one canvas + all its statements in order.
```json
{
  "canvas": {"id": 1, "slug": "...", "name": "...", "frame_id": "a3-grid",
             "created_at": ..., "updated_at": ...},
  "statements": [
    {"id": 101, "seq": 0, "opcode": "mr", "args": "14,0", "group_id": null},
    {"id": 102, "seq": 1, "opcode": "dl", "args": "1224,0", "group_id": null},
    ...
  ]
}
```

### `GET /api/canvases/{id_or_slug}/program`
Reconstruct and return the joined drawlang source as text (Content-Type:
`text/plain`). Useful for debugging + for driving the existing `/render`
endpoint from a canvas.

### `POST /api/canvases/{id_or_slug}/render`
Render the canvas by joining its statements and running the interpreter.
Response mirrors `/render`: `{"ok": true, "output": "<svg …>"}`.

## Writes come in Step 4

Step 3 seeds the DB from frame files (so there's something to read); it does
NOT expose statement create/update/delete. That's Step 4.

## Test coverage (Step 3)

- Schema applies idempotently.
- Empty DB: `GET /api/canvases` returns `{"canvases": []}`.
- Seed a canvas from `a3-grid` frame source: `GET /api/canvases/a3-grid-copy`
  returns 469 statements in order.
- `GET /api/canvases/a3-grid-copy/program` round-trips to a byte-identical
  program that renders to a byte-identical SVG.
- `POST /api/canvases/a3-grid-copy/render` returns SVG containing
  `BM Global A.S.` and zero `SIEMENS`.
