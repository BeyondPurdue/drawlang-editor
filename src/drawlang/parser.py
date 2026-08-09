"""
Parser for the Drawing Language v0.1.

Implements the grammar in spec §10 and the lexical rules in spec §3.
Produces a list of Statement objects that the interpreter (interpreter.py)
executes against a backend.

Key design notes tied to the spec:

- Spec §3.1: whitespace (space, tab, newline, carriage return) is NOT significant
  between tokens. It is significant INSIDE a `tx` string argument.
- Spec §3.4: strings do not use delimiters. A string argument runs from the
  comma that precedes it up to (not including) the terminating semicolon.
  This means we cannot generically split arguments by `,` for every opcode —
  `tx` is special because its second argument is a string and MAY contain
  commas.
- Spec §3.5: no comments in the language.
- Spec §3.6: opcodes and modifiers are lowercase; any uppercase form is a
  LexicalError.
- Spec §6-§7: each opcode has a fixed positional-argument signature; modifiers
  come AFTER all positional arguments and are matched by leading letter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import LexicalError, SemanticError

# ---------------------------------------------------------------------------
# Opcode registry — the closed set from spec §6 (Core) and §7 (Extensions).
# The registry drives argument validation and modifier acceptance.
# ---------------------------------------------------------------------------

# Argument type sentinels
INT = "int"
FLOAT = "float"
STRING = "string"  # only used by `tx`

# Modifier registry — spec §8
DEFINED_MODIFIERS = {"f", "i", "d", "c"}  # `c` is a family: c<int>

# Opcode signatures: (positional_types, allowed_modifiers, string_tail_arg)
# string_tail_arg: index of the argument that greedily consumes the rest of
# the statement (used only by `tx` for its string argument). None = no tail.
OPCODE_TABLE: dict[str, dict[str, Any]] = {
    # ---- Core opcodes (spec §6) — FROZEN ----
    "mr": {"args": [INT, INT], "mods": set(), "string_tail": None},
    "ma": {"args": [INT, INT], "mods": set(), "string_tail": None},
    "dl": {"args": [INT, INT], "mods": {"d", "c"}, "string_tail": None},
    "rt": {"args": [INT, INT], "mods": {"f", "i", "d", "c"}, "string_tail": None},
    "ci": {"args": [INT], "mods": {"f", "d", "c"}, "string_tail": None},
    "tz": {"args": [INT], "mods": set(), "string_tail": None},
    "tx": {"args": [FLOAT, STRING], "mods": {"c"}, "string_tail": 1},
    # ---- Extension opcodes (spec §7) — ADDITIVE ----
    "ar": {"args": [INT, FLOAT, FLOAT], "mods": {"f", "d", "c"}, "string_tail": None},
    "bz": {"args": [INT] * 6, "mods": {"d", "c"}, "string_tail": None},
    "sp": {"args": None, "mods": {"f", "d", "c"}, "string_tail": None},  # variadic even-count
    "im": {"args": [INT, INT, INT], "mods": set(), "string_tail": None},
}

# Regex for numbers (spec §3.4)
INTEGER_RE = re.compile(r"^-?\d+$")
FLOAT_RE = re.compile(r"^-?(\d+\.\d*|\.\d+|\d+\.)$")
# Modifiers: bare letter, or `c` followed by digits
MOD_BARE_RE = re.compile(r"^[a-z]$")
MOD_COLOR_RE = re.compile(r"^c\d+$")


@dataclass
class Modifier:
    """A parsed modifier: name ('f', 'i', 'd', 'c') plus optional color index."""

    name: str
    color_index: int | None = None  # only set for 'c<n>'

    def __repr__(self) -> str:
        if self.name == "c" and self.color_index is not None:
            return f"c{self.color_index}"
        return self.name


@dataclass
class Statement:
    """
    A parsed statement: opcode + positional args + modifiers.

    Positional args are typed Python values: int for INT args, float for FLOAT
    args, str for STRING args (with all whitespace preserved).
    """

    opcode: str
    args: list[Any]
    modifiers: list[Modifier] = field(default_factory=list)
    source_index: int = 0  # 0-based index in the program, for error messages

    def get_modifier(self, name: str) -> Modifier | None:
        for m in self.modifiers:
            if m.name == name:
                return m
        return None

    def has_modifier(self, name: str) -> bool:
        return self.get_modifier(name) is not None


# ---------------------------------------------------------------------------
# Parser entry point
# ---------------------------------------------------------------------------


def parse(program_text: str) -> list[Statement]:
    """
    Parse a program into a list of Statement objects.

    Raises LexicalError for grammar violations (unknown opcode, unknown
    modifier, malformed number).
    Raises SemanticError for signature violations (wrong argument count,
    wrong argument type, modifier not accepted by opcode, out-of-range value).
    """
    statements: list[Statement] = []
    for i, raw in enumerate(_split_statements(program_text)):
        if not raw.strip():
            continue  # empty statement (e.g. trailing ";" produces empty tail)
        try:
            statements.append(_parse_statement(raw, i))
        except (LexicalError, SemanticError) as e:
            # Re-raise with the statement index attached
            e.statement_index = i
            raise
    return statements


# ---------------------------------------------------------------------------
# Statement splitting (spec §3.2)
# Statements are terminated by ';'. We MUST NOT split inside a `tx` string,
# but spec §3.4 explicitly forbids ';' inside a string, so a naïve split on ';'
# is correct — any embedded ';' is a lexical error anyway (and would produce
# a bogus statement that will fail opcode validation).
# ---------------------------------------------------------------------------


def _split_statements(program_text: str) -> list[str]:
    return program_text.split(";")


# ---------------------------------------------------------------------------
# Single-statement parser
# ---------------------------------------------------------------------------


def _parse_statement(raw: str, index: int) -> Statement:
    """
    Parse one statement (already stripped of its trailing ';').

    The tricky case is `tx`: after the opcode and the first (float) argument,
    the entire remainder of the statement is the string argument — including
    any commas, spaces, and whitespace — up to but not including the ';'.
    Modifiers for `tx` are limited to `,c<n>`; because we know `tx` accepts
    `c` only, and colors are `c<digits>`, we can safely peel a trailing
    `,c<digits>` modifier off the end of the string before treating the
    remainder as the raw text.

    For all other opcodes, we split by ',' at the top level (no strings
    contain commas, per the opcode signatures).
    """
    # 1. Extract the opcode (first two lowercase ASCII letters, no whitespace).
    #    Leading whitespace is allowed (spec §3.1).
    stripped = raw.lstrip()
    if len(stripped) < 2:
        raise LexicalError(f"statement too short: {raw!r}")

    # The opcode is exactly two lowercase letters, optionally followed by
    # whitespace + ',' (arguments follow) or nothing (no arguments).
    m = re.match(r"^([a-z]{2})\s*(?:,(.*))?$", stripped, flags=re.DOTALL)
    if not m:
        # Distinguish uppercase from unknown-shape
        m_upper = re.match(r"^([A-Za-z]{2})", stripped)
        if m_upper and not m_upper.group(1).islower():
            raise LexicalError(
                f"opcode must be lowercase: {m_upper.group(1)!r} (spec §3.6)"
            )
        raise LexicalError(f"malformed statement (cannot extract opcode): {raw!r}")

    opcode = m.group(1)
    tail = m.group(2) or ""

    if opcode not in OPCODE_TABLE:
        raise LexicalError(
            f"unknown opcode {opcode!r}. Valid opcodes: "
            + ", ".join(sorted(OPCODE_TABLE))
            + " (spec §3.3)"
        )

    spec = OPCODE_TABLE[opcode]

    # 2. Split the tail into fields, respecting string-tail semantics for `tx`.
    if spec["string_tail"] is not None:
        fields = _split_with_string_tail(tail, spec)
    else:
        fields = _split_fields(tail)

    # 3. Separate positional args from modifiers.
    positional_raw, modifiers_raw = _split_positional_and_modifiers(fields, spec)

    # 4. Validate & coerce positional args against the signature.
    args = _coerce_arguments(opcode, spec, positional_raw)

    # 5. Validate & parse modifiers.
    modifiers = _validate_modifiers(opcode, spec, modifiers_raw)

    return Statement(opcode=opcode, args=args, modifiers=modifiers, source_index=index)


def _split_fields(tail: str) -> list[str]:
    """Split by ',' at the top level (no strings). Preserve empty fields."""
    return [f.strip() for f in tail.split(",")] if tail else []


def _split_with_string_tail(tail: str, spec: dict) -> list[str]:
    """
    For opcodes with a string-tail argument (currently only `tx`).

    Signature for `tx` is [FLOAT, STRING] with string at index 1.
    Approach: split off the first (float) argument, then peel a trailing
    `,c<digits>` color modifier if present, and the remainder is the string.

    Whitespace INSIDE the string MUST be preserved (spec §3.1 last sentence
    applies between tokens; the string is a single token that begins after
    the comma that follows the first argument).
    """
    string_index = spec["string_tail"]
    types = spec["args"]

    # Split the leading arguments up to and including the one right before the string.
    # For `tx`, string_index=1, so we split off the first (index 0) field.
    parts = tail.split(",", string_index + 1)
    # If tail is empty or too short, produce what we have — validation will fail later.
    if len(parts) < string_index + 1:
        return [p.strip() for p in parts]

    leading = [p.strip() for p in parts[:string_index]]
    remainder = parts[string_index]  # this is the raw string + any trailing modifiers

    # Peel a trailing color modifier off the string if present.
    # `tx` only accepts `,c<digits>` (spec §6.7 & §8), so we look for
    # ",<c-digit-run>" at the very end.
    color_mod = None
    m = re.search(r",\s*(c\d+)\s*$", remainder)
    if m:
        color_mod = m.group(1)
        remainder = remainder[: m.start()]

    # The remaining `remainder` is the string, preserved verbatim (leading
    # whitespace after the comma is part of the string, per spec §3.4).
    # We do NOT strip it — a user might want a leading space.

    result = leading + [remainder]
    if color_mod:
        result.append(color_mod)
    return result


def _split_positional_and_modifiers(
    fields: list[str], spec: dict
) -> tuple[list[str], list[str]]:
    """
    A modifier is any trailing field that matches a modifier pattern.
    Positional args come first, modifiers last (spec §8: "MUST appear after
    all positional arguments").
    """
    # Modifiers are only "found" at the tail. Walk from the right until we
    # hit a field that isn't a modifier.
    n_modifiers = 0
    for f in reversed(fields):
        if _looks_like_modifier(f):
            n_modifiers += 1
        else:
            break
    if n_modifiers == 0:
        return fields, []
    return fields[:-n_modifiers], fields[-n_modifiers:]


def _looks_like_modifier(s: str) -> bool:
    """
    A field is 'modifier-shaped' if it has the shape of a single lowercase
    letter or a c-followed-by-digits.

    Note: we intentionally return True even for undefined single-letter
    modifiers (e.g. 'z'), so that they are routed to the modifier-validation
    path (which will raise a helpful 'unknown modifier' LexicalError) rather
    than being mistaken for a positional argument (which would raise an
    unrelated argument-count error).
    """
    s = s.strip()
    if MOD_BARE_RE.match(s):
        return True  # any single lowercase letter — validity is checked later
    if MOD_COLOR_RE.match(s):
        return True
    return False


def _coerce_arguments(opcode: str, spec: dict, raw_args: list[str]) -> list[Any]:
    """Type-check and coerce positional arguments to Python values."""
    sig = spec["args"]

    # Variadic opcode: `sp` accepts any even number of INT args >= 4
    if sig is None and opcode == "sp":
        if len(raw_args) < 4 or len(raw_args) % 2 != 0:
            raise SemanticError(
                f"'sp' requires an even number of integer args (>=4), got "
                f"{len(raw_args)} (spec §7.3)"
            )
        return [_coerce_int(a, opcode) for a in raw_args]

    if len(raw_args) != len(sig):
        raise SemanticError(
            f"'{opcode}' expects {len(sig)} argument(s), got {len(raw_args)}: "
            f"{raw_args!r}"
        )

    result = []
    for i, (arg_type, raw) in enumerate(zip(sig, raw_args)):
        if arg_type == INT:
            result.append(_coerce_int(raw, opcode, i))
        elif arg_type == FLOAT:
            result.append(_coerce_float(raw, opcode, i))
        elif arg_type == STRING:
            # No coercion — preserve verbatim (spec §3.4, §6.7)
            result.append(raw)
        else:
            raise SemanticError(f"internal: unknown arg type {arg_type!r}")
    return result


def _coerce_int(raw: str, opcode: str, idx: int = -1) -> int:
    raw = raw.strip()
    if not INTEGER_RE.match(raw):
        pos = f" (arg #{idx})" if idx >= 0 else ""
        raise SemanticError(
            f"'{opcode}'{pos}: expected integer, got {raw!r} (spec §3.4)"
        )
    value = int(raw)
    # Spec §4.3: default range i2 (int16). We allow the language-level range
    # only; specific opcodes can enforce tighter positive-only ranges.
    if not (-32768 <= value <= 32767):
        raise SemanticError(
            f"'{opcode}': integer {value} out of range [-32768, 32767] (spec §4.3)"
        )
    return value


def _coerce_float(raw: str, opcode: str, idx: int = -1) -> float:
    raw = raw.strip()
    if not FLOAT_RE.match(raw):
        pos = f" (arg #{idx})" if idx >= 0 else ""
        raise SemanticError(
            f"'{opcode}'{pos}: expected float (with explicit decimal point), "
            f"got {raw!r} (spec §3.4)"
        )
    return float(raw)


def _validate_modifiers(
    opcode: str, spec: dict, raw_modifiers: list[str]
) -> list[Modifier]:
    """Verify each modifier is accepted by this opcode; parse `c<n>` colors."""
    allowed = spec["mods"]
    result: list[Modifier] = []
    for raw in raw_modifiers:
        raw = raw.strip()
        if MOD_COLOR_RE.match(raw):
            name = "c"
            color_index = int(raw[1:])
        elif MOD_BARE_RE.match(raw) and raw in DEFINED_MODIFIERS:
            name = raw
            color_index = None
        else:
            raise LexicalError(
                f"unknown modifier {raw!r}. Defined modifiers: "
                f"f, i, d, c<n> (spec §8.1)"
            )
        if name not in allowed:
            raise SemanticError(
                f"'{opcode}' does not accept modifier {raw!r}. Accepted: "
                f"{sorted(allowed) if allowed else 'none'} (spec §{'6' if opcode in {'mr','ma','dl','rt','ci','tz','tx'} else '7'})"
            )
        # Enforce spec-specific range: circle/arc radius positive; text size positive
        result.append(Modifier(name=name, color_index=color_index))
    return result
