"""
gmf_parser.py — Reference parser for legacy .gmf drawing archive files.

Grounded in 15 real production files from project 4640
(YFR "individual level" DTK=1 and YFH "overview level" DTK=3).

Grammar summary
---------------
File   := banner_line NEWLINE  program
banner := format_marker WS sheet_size WS source_path
           # format_marker is either "drawlang" (current) or the legacy
           # marker used by older backup archives, accepted for compatibility
program := (statement)*
statement := opcode ("," arg)* ";"

Opcodes seen in production (all 9):

  ma  x,y             move absolute
  mr  dx,dy           move relative
  dl  dx,dy [,i]      draw line relative; optional 'i' modifier = invisible/metadata
  rt  w,h [,f]        rectangle from current pen; optional 'f' = filled
  ci  r,{t|f}         circle at current pen; 2nd arg is flag letter (t=?, f=filled)
  tz  size            set text size
  tx  angle,text      draw text at current pen; text runs verbatim to ';'
  sb                  scope begin (start block/symbol)
  eb                  scope end   (end block/symbol)

Two additional lexical facts extracted from real files:
  * "ma,0,0;" is used as an inter-pictogram separator (very common)
  * A ';' inside a text string does not occur in the 15-file corpus;
    however a ',' inside a text string DOES occur. So tx MUST be tokenised
    specially: after the 2nd argument delimiter, take everything up to the
    next ';' as the literal string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Banner:
    format: str          # "drawlang" or legacy marker
    sheet_size: str      # "A4"
    source_path: str     # e.g. "/tmp/get_gmf/legacy/4640.1.99ada11gs010m.gmf"

    @property
    def project(self) -> str | None:
        """Extract project number from the source path filename, e.g. '4640'."""
        base = Path(self.source_path).stem   # 4640.1.99ada11gs010m
        return base.split(".", 1)[0] if base else None

    @property
    def dtk_num(self) -> int | None:
        """Extract the DTK numeric field (2nd dot-separated field), e.g. 1 or 3."""
        base = Path(self.source_path).stem
        parts = base.split(".")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
        return None

    @property
    def kks(self) -> str | None:
        """Everything after the DTK field is the KKS designator."""
        base = Path(self.source_path).stem
        parts = base.split(".", 2)
        return parts[2] if len(parts) >= 3 else None


@dataclass
class Statement:
    opcode: str
    args: list          # elements are int, float, or str (for text/flags)
    modifier: str | None = None   # 'f', 'i', 't' etc. — separated from geometric args

    def __repr__(self) -> str:
        m = f",{self.modifier}" if self.modifier else ""
        return f"{self.opcode}({','.join(map(str, self.args))}{m})"


@dataclass
class Block:
    """A group of statements between an sb/eb pair."""
    statements: list = field(default_factory=list)   # Statement or Block


@dataclass
class Program:
    banner: Banner
    body: list = field(default_factory=list)         # Statement or Block (flat + nested)

    @property
    def all_statements(self) -> Iterable[Statement]:
        """Depth-first flatten of all statements, ignoring block boundaries."""
        def walk(nodes):
            for n in nodes:
                if isinstance(n, Block):
                    yield from walk(n.statements)
                else:
                    yield n
        yield from walk(self.body)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# opcodes whose 2nd (post-geometry) arg may be a letter modifier
_MODIFIER_LETTERS = {'f', 'i', 't'}

_OPCODES = {'ma', 'mr', 'dl', 'rt', 'ci', 'tz', 'tx', 'sb', 'eb'}

# banner: "<format_marker> <size> <path>"
# Accepts current marker ("drawlang") and legacy marker ("es680") for
# backward compatibility with archived backup files.
_BANNER_RE = re.compile(r'^(drawlang|es680)\s+(\S+)\s+(.+?)\s*$')

# opcode at the start of a statement; whitespace-tolerant
_OP_RE = re.compile(r'\s*([a-z]{2})\s*')


class GmfParseError(ValueError):
    pass


def _parse_number(tok: str):
    tok = tok.strip()
    if re.match(r'^-?\d+$', tok):
        return int(tok)
    if re.match(r'^-?\d+\.\d*$', tok) or re.match(r'^-?\.\d+$', tok):
        return float(tok)
    return None


def _split_top_level(text: str) -> list[str]:
    """Split the body into statements at ';', ignoring nothing (there are no
    escapes; ';' never appears inside a tx text string in the corpus)."""
    parts = [p.strip() for p in text.split(';')]
    return [p for p in parts if p]


def _parse_statement(raw: str) -> Statement:
    """Parse one already-';'-stripped statement string."""
    m = _OP_RE.match(raw)
    if not m:
        raise GmfParseError(f"no opcode at start of statement: {raw!r}")
    op = m.group(1)
    if op not in _OPCODES:
        raise GmfParseError(f"unknown opcode {op!r} in: {raw!r}")

    rest = raw[m.end():].lstrip()
    if not rest:
        return Statement(opcode=op, args=[])
    if not rest.startswith(','):
        raise GmfParseError(f"expected ',' after opcode {op!r}: {raw!r}")
    rest = rest[1:]  # drop the leading ','

    # tx: angle, then literal text (may contain commas)
    if op == 'tx':
        comma = rest.find(',')
        if comma < 0:
            raise GmfParseError(f"tx missing text field: {raw!r}")
        angle_tok = rest[:comma].strip()
        text = rest[comma + 1:]  # verbatim, may contain commas / spaces
        angle = _parse_number(angle_tok)
        if angle is None:
            raise GmfParseError(f"tx angle not numeric: {angle_tok!r}")
        return Statement(opcode='tx', args=[angle, text])

    # Everyone else: comma-separated fields
    tokens = [t.strip() for t in rest.split(',')]
    args, modifier = [], None

    for i, tok in enumerate(tokens):
        num = _parse_number(tok)
        if num is not None:
            args.append(num)
        elif len(tok) == 1 and tok in _MODIFIER_LETTERS:
            # last-position flag; nothing may come after
            if i != len(tokens) - 1:
                raise GmfParseError(f"modifier {tok!r} not in last position: {raw!r}")
            modifier = tok
        else:
            raise GmfParseError(f"unexpected token {tok!r} in: {raw!r}")

    # Per-opcode arity validation (based on the 15-file corpus)
    expected = {
        'ma': (2, False), 'mr': (2, False),
        'dl': (2, True),  'rt': (2, True),
        'ci': (1, True),  'tz': (1, False),
    }
    if op in expected:
        nargs, mod_ok = expected[op]
        if len(args) != nargs:
            raise GmfParseError(
                f"{op} expects {nargs} numeric args, got {len(args)}: {raw!r}")
        if modifier and not mod_ok:
            raise GmfParseError(f"{op} does not take a modifier: {raw!r}")

    return Statement(opcode=op, args=args, modifier=modifier)


def parse(text: str) -> Program:
    """Parse a full .gmf file (banner + program)."""
    lines = text.splitlines()
    if not lines:
        raise GmfParseError("empty file")

    m = _BANNER_RE.match(lines[0])
    if not m:
        raise GmfParseError(f"bad banner line: {lines[0]!r}")
    banner = Banner(format=m.group(1), sheet_size=m.group(2), source_path=m.group(3))

    body_text = '\n'.join(lines[1:])
    stmts = [_parse_statement(s) for s in _split_top_level(body_text)]

    # Fold sb/eb into nested Block scopes
    root: list = []
    stack: list[list] = [root]
    for s in stmts:
        if s.opcode == 'sb':
            new_block = Block()
            stack[-1].append(new_block)
            stack.append(new_block.statements)
        elif s.opcode == 'eb':
            if len(stack) == 1:
                raise GmfParseError("eb without matching sb")
            stack.pop()
        else:
            stack[-1].append(s)
    if len(stack) != 1:
        raise GmfParseError(f"{len(stack)-1} unclosed sb block(s)")

    return Program(banner=banner, body=root)


def parse_file(path: str | Path) -> Program:
    return parse(Path(path).read_text())


# ---------------------------------------------------------------------------
# Statistics / inspection helpers
# ---------------------------------------------------------------------------

def opcode_counts(prog: Program) -> dict[str, int]:
    from collections import Counter
    c = Counter(s.opcode for s in prog.all_statements)
    # include sb/eb by counting Block nodes
    def count_blocks(nodes):
        n = 0
        for x in nodes:
            if isinstance(x, Block):
                n += 1
                n += count_blocks(x.statements)
        return n
    b = count_blocks(prog.body)
    if b:
        c['sb'] = b
        c['eb'] = b
    return dict(c)


def bounding_box(prog: Program) -> tuple[int, int, int, int]:
    """Walk the program with a pen simulator and return (xmin,ymin,xmax,ymax)."""
    px = py = 0
    xs = [0]; ys = [0]
    for s in prog.all_statements:
        if s.opcode == 'ma':
            px, py = s.args
        elif s.opcode == 'mr':
            px += s.args[0]; py += s.args[1]
        elif s.opcode == 'dl':
            nx, ny = px + s.args[0], py + s.args[1]
            xs.extend([px, nx]); ys.extend([py, ny])
            px, py = nx, ny
        elif s.opcode == 'rt':
            w, h = s.args
            xs.extend([px, px + w]); ys.extend([py, py + h])
        elif s.opcode == 'ci':
            r = s.args[0]
            xs.extend([px - r, px + r]); ys.extend([py - r, py + r])
        elif s.opcode == 'tx':
            xs.append(px); ys.append(py)   # tx does not advance the pen
        xs.append(px); ys.append(py)
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("usage: python gmf_parser.py <file.gmf> [file2.gmf ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        prog = parse_file(path)
        counts = opcode_counts(prog)
        bbox = bounding_box(prog)
        print(f"\n== {path} ==")
        print(f"  banner: format={prog.banner.format} sheet={prog.banner.sheet_size}")
        print(f"  project={prog.banner.project}  DTK#={prog.banner.dtk_num}  KKS={prog.banner.kks}")
        print(f"  opcode counts: {counts}")
        print(f"  bbox: {bbox}")
        print(f"  top-level nodes: {len(prog.body)}")
