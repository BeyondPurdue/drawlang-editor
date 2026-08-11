"""
Editor-only SVG backend wrapper that tags each emitted element with the
source statement's row id, so the frontend can round-trip clicks between
the rendered canvas and the statements list.

The language layer is UNCHANGED. The stock `SVGBackend` still knows
nothing about statement ids. This class subclasses it and intercepts
`_body_parts.append` to wrap each new element in
`<g data-statement-id="N">…</g>` where N is the interpreter's current
statement source_index.

Usage in the render endpoint:

    backend = TaggedSVGBackend(width=..., height=...)
    run(parsed_statements, backend, tagger=backend.set_current_statement)

where `run(...)` is a thin wrapper around the standard interpreter that
notifies the tagger before dispatching each statement.

This keeps Principle 5 (output-format neutrality) intact: nothing about
statement ids leaks into the shared SVG backend or the interpreter's
public contract. Editor concerns stay in the editor package.
"""

from __future__ import annotations

from typing import Any

from drawlang.backends.svg import SVGBackend
from drawlang.interpreter import PenState, _execute  # editor-internal reuse
from drawlang.parser import parse


class TaggedSVGBackend(SVGBackend):
    """SVGBackend that groups each emitted element under a statement id.

    The `set_current_statement(stmt)` hook is called by `run_tagged` before
    each statement executes. Whenever the language layer appends a new
    element to `_body_parts`, we wrap that element in a `<g data-
    statement-id="N">` where N is the last-set statement's row id. A
    single statement can emit multiple primitive elements (e.g. filled
    circle + outline circle); they all share the same wrapper.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Map from source_index -> row id (assigned by the editor when it
        # composes the program from DB rows). Filled by the caller before
        # calling run_tagged.
        self._source_to_row: dict[int, int] = {}
        self._current_row: int | None = None
        # We monkeypatch the underlying list so append() re-writes each
        # new fragment. Simpler than subclassing list.
        self._raw_parts = self._body_parts
        self._body_parts = _TaggedList(self)

    def set_source_to_row_map(self, mapping: dict[int, int]) -> None:
        """Set the source_index -> row id mapping for this render pass."""
        self._source_to_row = dict(mapping)

    def set_current_statement(self, stmt: Any) -> None:
        """Called by run_tagged before each statement executes."""
        src = getattr(stmt, "source_index", None)
        self._current_row = self._source_to_row.get(src) if src is not None else None

    # Overriding finalize is unnecessary; the base class calls
    # `''.join(self._body_parts)` — our _TaggedList joins as a plain list.


class _TaggedList(list):
    """A list that wraps each appended fragment with the current statement id."""

    def __init__(self, backend: TaggedSVGBackend):
        super().__init__()
        self._backend = backend

    def append(self, fragment: str) -> None:
        row = self._backend._current_row
        if row is not None:
            fragment = f'<g data-statement-id="{row}">{fragment}</g>'
        super().append(fragment)


def run_tagged(
    program_text: str,
    backend: TaggedSVGBackend,
) -> str:
    """Parse `program_text`, execute against `backend`, return the SVG.

    Uses the standard interpreter under the hood but calls the tagger hook
    before every statement so the backend knows which row to attribute
    each emitted element to. The caller must have already populated the
    source_index -> row id mapping via `set_source_to_row_map`.
    """
    stmts = parse(program_text)
    pen = PenState()
    for stmt in stmts:
        backend.set_current_statement(stmt)
        _execute(stmt, pen, backend)
    return backend.finalize()
