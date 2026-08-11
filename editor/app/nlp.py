"""
Natural-language → drawlang statement translator.

KISS: no external LLM. A grammar of ~30 phrase patterns handles the
core opcodes. Unknown phrases are rejected with a helpful hint.

The user types (or speaks) plain English/Czech commands into a single
input field; each command becomes one or more drawlang statements
which are appended to the current canvas via /api/canvases/.../statements.

Supported patterns
------------------
- "move to X Y" / "move absolute X Y"          -> ma,X,Y
- "move right N" / "move left N"                -> mr,+N,0 / mr,-N,0
- "move up N"    / "move down N"                -> mr,0,-N / mr,0,+N
- "move relative X Y"                           -> mr,X,Y
- "line right N" / "line left N"                -> dl,+N,0 / dl,-N,0
- "line up N"    / "line down N"                -> dl,0,-N / dl,0,+N
- "line to relative X Y"                        -> dl,X,Y
- "line to absolute X Y" / "line to X Y"        -> da,X,Y
- "rectangle W H" / "rect W H"                  -> rt,W,H
- "circle R"                                    -> ci,R
- "text ANGLE STRING" / "write ANGLE STRING"    -> tx,ANGLE,STRING
- "text STRING"                                 -> tx,0,STRING
- "pen thickness N" / "thickness N"             -> pt,N
- Multiple commands separated by "and" or ";"
"""

from __future__ import annotations

import re


class NLPError(ValueError):
    pass


_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "nula": 0, "jedna": 1, "dva": 2, "tri": 3, "tři": 3, "ctyri": 4, "čtyři": 4,
    "pet": 5, "pět": 5, "sest": 6, "šest": 6, "sedm": 7, "osm": 8,
    "devet": 9, "devět": 9, "deset": 10,
}


def _parse_num(tok: str) -> float:
    tok = tok.lower().strip()
    if tok in _NUM_WORDS:
        return float(_NUM_WORDS[tok])
    try:
        return float(tok)
    except ValueError:
        raise NLPError(f"expected a number, got {tok!r}")


def _fmt(n: float) -> str:
    if float(n).is_integer():
        return str(int(n))
    return str(n)


def translate_command(text: str) -> list[str]:
    """
    Translate a plain-English command into a list of drawlang statements
    (each already terminated by ;).
    """
    t = text.strip().rstrip(";").lower()
    if not t:
        return []

    # Split on "and" or ";" for compound commands.
    parts = re.split(r"\s+and\s+|;", t)
    stmts: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        stmts.extend(_translate_single(part, text))
    return stmts


def _translate_single(t: str, original: str) -> list[str]:
    # Move absolute
    m = re.match(r"move (?:to |absolute |absolutne |na )([-\d.]+)[ ,]+([-\d.]+)$", t)
    if m:
        return [f"ma,{_fmt(_parse_num(m.group(1)))},{_fmt(_parse_num(m.group(2)))};"]

    # Move directional
    m = re.match(r"(?:move|jdi|posun) (right|left|up|down|doprava|doleva|nahoru|dolu|dolů)\s+(\S+)$", t)
    if m:
        d, n = m.group(1), _parse_num(m.group(2))
        if d in ("right", "doprava"): return [f"mr,{_fmt(n)},0;"]
        if d in ("left", "doleva"):   return [f"mr,{_fmt(-n)},0;"]
        if d in ("up", "nahoru"):     return [f"mr,0,{_fmt(-n)};"]
        if d in ("down", "dolu", "dolů"): return [f"mr,0,{_fmt(n)};"]

    # Move relative XY
    m = re.match(r"move (?:relative |relativne |o )([-\d.]+)[ ,]+([-\d.]+)$", t)
    if m:
        return [f"mr,{_fmt(_parse_num(m.group(1)))},{_fmt(_parse_num(m.group(2)))};"]

    # Line directional
    m = re.match(r"(?:line|draw|kresli|nakresli) (right|left|up|down|doprava|doleva|nahoru|dolu|dolů)\s+(\S+)$", t)
    if m:
        d, n = m.group(1), _parse_num(m.group(2))
        if d in ("right", "doprava"): return [f"dl,{_fmt(n)},0;"]
        if d in ("left", "doleva"):   return [f"dl,{_fmt(-n)},0;"]
        if d in ("up", "nahoru"):     return [f"dl,0,{_fmt(-n)};"]
        if d in ("down", "dolu", "dolů"): return [f"dl,0,{_fmt(n)};"]

    # Line to absolute
    m = re.match(r"(?:line|draw) to (?:absolute |na )?([-\d.]+)[ ,]+([-\d.]+)$", t)
    if m:
        return [f"da,{_fmt(_parse_num(m.group(1)))},{_fmt(_parse_num(m.group(2)))};"]

    # Line to relative
    m = re.match(r"(?:line|draw) (?:to )?relative\s+([-\d.]+)[ ,]+([-\d.]+)$", t)
    if m:
        return [f"dl,{_fmt(_parse_num(m.group(1)))},{_fmt(_parse_num(m.group(2)))};"]

    # Rectangle
    m = re.match(r"(?:rectangle|rect|obdelnik|obdélník)\s+([-\d.]+)[ ,]+([-\d.]+)$", t)
    if m:
        return [f"rt,{_fmt(_parse_num(m.group(1)))},{_fmt(_parse_num(m.group(2)))};"]

    # Circle
    m = re.match(r"(?:circle|kruh)\s+([-\d.]+)$", t)
    if m:
        return [f"ci,{_fmt(_parse_num(m.group(1)))};"]

    # Text with explicit angle
    m = re.match(r"(?:text|write|napis|napiš)\s+([-\d.]+)\s+(.+)$", t, re.IGNORECASE)
    if m:
        # Get original casing of the text arg
        orig_match = re.search(
            rf"(?:text|write|napis|napiš)\s+{re.escape(m.group(1))}\s+(.+?)(?:;|$)",
            original, re.IGNORECASE,
        )
        text_arg = orig_match.group(1).strip() if orig_match else m.group(2)
        return [f"tx,{_fmt(_parse_num(m.group(1)))},{text_arg};"]

    # Text with no angle
    m = re.match(r"(?:text|write|napis|napiš)\s+(.+)$", t, re.IGNORECASE)
    if m:
        orig_match = re.search(
            r"(?:text|write|napis|napiš)\s+(.+?)(?:;|$)", original, re.IGNORECASE
        )
        text_arg = orig_match.group(1).strip() if orig_match else m.group(1)
        return [f"tx,0,{text_arg};"]

    # Pen thickness
    m = re.match(r"(?:pen thickness|thickness|tloustka|tloušťka)\s+(\S+)$", t)
    if m:
        return [f"pt,{_fmt(_parse_num(m.group(1)))};"]

    # Raw drawlang passthrough (opcode,args) if it already looks like drawlang
    if re.match(r"^[a-z]{2},.+$", t):
        return [t.rstrip(";") + ";"]

    raise NLPError(
        f"can't translate {t!r} — try: 'move right 20', 'line down 30', "
        f"'rect 100 50', 'circle 10', 'text 0 hello', or raw drawlang like 'mr,20,0'"
    )


__all__ = ["translate_command", "NLPError"]
