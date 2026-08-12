"""
Natural-language selection-transform parser.

Recognises phrases like:
    - move right 50
    - shift the selection to the left by 20 pixels
    - go up 5
    - bigger 20%           -> scale factor 1.2
    - smaller 10%          -> scale factor 0.9
    - bigger                -> default factor 1.1
    - scale 0.5
    - scale to 150%        -> scale factor 1.5
    - double the size      -> scale factor 2
    - half the size        -> scale factor 0.5

Returns a dict describing an action to apply to the current selection.
The frontend is responsible for calling nudgeSelection / scaleSelection
with the returned parameters.

If nothing matches, raises SelectionCommandError; the caller is expected
to fall back to the general NLP translator or an LLM.

KISS design:
    * regex-only
    * english + a few czech aliases
    * numbers are integers (paper mm) for shifts, floats for scale factors
    * ambiguous words like "size" or "resize" are handled
"""

from __future__ import annotations

import re


class SelectionCommandError(ValueError):
    pass


# Number-word map, mirrors the NLP module so voice input works.
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "half": 0.5, "double": 2.0, "twice": 2.0, "triple": 3.0,
    "nula": 0, "jedna": 1, "dva": 2, "tri": 3, "tři": 3,
    "ctyri": 4, "čtyři": 4, "pet": 5, "pět": 5, "sest": 6, "šest": 6,
    "sedm": 7, "osm": 8, "devet": 9, "devět": 9, "deset": 10,
}


def _num(tok: str) -> float:
    tok = tok.lower().strip().rstrip("%").rstrip(",.")
    if tok in _NUM_WORDS:
        return float(_NUM_WORDS[tok])
    return float(tok)


_DIR_MAP = {
    # english
    "right": (1, 0), "left": (-1, 0), "up": (0, 1), "down": (0, -1),
    # czech
    "doprava": (1, 0), "doleva": (-1, 0),
    "nahoru": (0, 1), "dolu": (0, -1), "dolů": (0, -1),
}


def parse(text: str) -> dict:
    """Parse a selection command. Returns:
        {"op": "shift",  "dx": int, "dy": int}
        {"op": "scale",  "factor": float}
    Raises SelectionCommandError on no match.
    """
    if not text or not text.strip():
        raise SelectionCommandError("empty command")
    t = text.strip().lower()
    # Strip filler words that whisper likes to sprinkle in.
    # Punctuation must be stripped separately — stripping '.' inside numbers
    # like 0.5 would break scale factors.
    t = re.sub(r"[,;!?]", " ", t)
    # Trailing period only (end-of-sentence), never a decimal point.
    t = re.sub(r"\.\s", " ", t)
    t = re.sub(r"\.$", "", t)
    t = re.sub(
        r"\b(please|the|a|it|them|selection|selected|object|objects|"
        r"shape|shapes|this|that)\b", " ", t,
    )
    t = re.sub(r"\s+", " ", t).strip()

    # --- SHIFT (move / go / shift / posun / jdi) --------------------------
    # "move right 50 pixels" / "shift left by 20" / "go up 5"
    m = re.search(
        r"\b(?:move|shift|go|nudge|jdi|posun)\b"
        r"(?:\s+(?:to|by|of|into|towards?))*\s*"
        r"(right|left|up|down|doprava|doleva|nahoru|dolu|dolů)"
        r"\s*(?:by\s+)?([-\d.]+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"twenty|thirty|forty|fifty|hundred)?"
        r"(?:\s*(?:px|pixels|pixel|mm|units))?",
        t,
    )
    if m:
        dxu, dyu = _DIR_MAP[m.group(1)]
        n = int(_num(m.group(2))) if m.group(2) else 10
        return {"op": "shift", "dx": dxu * n, "dy": dyu * n}

    # "left 20" / "right 5" without a leading verb
    m = re.match(
        r"^(right|left|up|down|doprava|doleva|nahoru|dolu|dolů)\s+"
        r"([-\d.]+|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"twenty|thirty|forty|fifty|hundred)\b",
        t,
    )
    if m:
        dxu, dyu = _DIR_MAP[m.group(1)]
        n = int(_num(m.group(2)))
        return {"op": "shift", "dx": dxu * n, "dy": dyu * n}

    # --- SCALE ------------------------------------------------------------
    # "double the size" / "twice as big" / "half the size"
    if re.search(r"\b(double|twice)\b", t):
        return {"op": "scale", "factor": 2.0}
    if re.search(r"\b(half|halve)\b", t):
        return {"op": "scale", "factor": 0.5}

    # "scale to 150%" / "scale 0.5"
    m = re.search(r"\bscale\s+(?:to\s+)?([-\d.]+)\s*(%)?", t)
    if m:
        v = _num(m.group(1))
        if m.group(2) or v > 5:   # 150 with % or >5 = probably percent
            v = v / 100.0
        if v <= 0:
            raise SelectionCommandError("scale factor must be positive")
        return {"op": "scale", "factor": float(v)}

    # "bigger 20%" / "smaller 10%" / "bigger" / "smaller"
    m = re.search(
        r"\b(bigger|larger|smaller|smaller|zoom in|zoom out|zvetsit|zmensit|"
        r"zvětšit|zmenšit)\b\s*(?:by\s+)?([-\d.]+)?\s*(%)?",
        t,
    )
    if m:
        direction = m.group(1)
        pct = float(m.group(2)) if m.group(2) else 10.0
        if pct <= 0:
            raise SelectionCommandError("scale percent must be positive")
        if direction in ("smaller", "zoom out", "zmensit", "zmenšit"):
            factor = max(0.01, 1.0 - pct / 100.0)
        else:
            factor = 1.0 + pct / 100.0
        return {"op": "scale", "factor": factor}

    raise SelectionCommandError(
        f"can't parse selection command {text!r} — try "
        f"'move right 50', 'up 20', 'bigger 20%', 'smaller 10%', 'scale 1.5'"
    )


__all__ = ["parse", "SelectionCommandError"]
