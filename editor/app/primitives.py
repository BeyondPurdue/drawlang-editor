"""Parametric primitive catalog.

Primitives are stored as JSON files under ``editor/primitives/``. Each file
describes one primitive: display metadata, a list of parameters, an optional
``compute`` map of derived expressions, and a drawlang ``template`` (or a
``template_variants`` map keyed by one of the params).

Expansion is deterministic: given the same params, the same drawlang bytes
are produced. Templates use ``{{name}}`` placeholders — no conditionals, no
loops. The ``compute`` block is a tiny safe expression evaluator over the
current params (plus a whitelisted set of builtins: ``len``, ``abs``,
``min``, ``max``, ``round``) — this is only enough to compute label
positions and mirrored coordinates, not general programs.

v0.6 drawlang stays LOCKED. Primitives are just a UI-level way to emit
sequences of v0.6 opcodes; no new opcodes are introduced.
"""
from __future__ import annotations

import ast
import json
import operator
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent  # editor/
_CATALOG_DIR = _ROOT / "primitives"

# ---------------------------------------------------------------------------
# Safe expression evaluator for the `compute` block
# ---------------------------------------------------------------------------

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_ALLOWED_CALLS = {
    "len": len,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
}


def _safe_eval(expr: str, env: dict) -> object:
    """Evaluate a tiny arithmetic expression against ``env``.

    Supported: numbers, strings, names (looked up in env), unary +/-,
    binary + - * / // % **, calls to whitelisted builtins.
    Raises ValueError on anything else.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"bad expression: {expr!r} ({e})")

    def _v(node):
        if isinstance(node, ast.Expression):
            return _v(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            raise ValueError(f"unknown name: {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](_v(node.left), _v(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](_v(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("only bare function names allowed")
            fname = node.func.id
            if fname not in _ALLOWED_CALLS:
                raise ValueError(f"call not allowed: {fname}")
            args = [_v(a) for a in node.args]
            return _ALLOWED_CALLS[fname](*args)
        raise ValueError(f"unsupported syntax: {ast.dump(node)}")

    return _v(tree)


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def _catalog_dir() -> Path:
    return _CATALOG_DIR


def list_primitives() -> list[dict]:
    """Return the catalog as a list of light-payload rows (no template)."""
    out = []
    for path in sorted(_catalog_dir().glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        out.append(
            {
                "id": data["id"],
                "name": data.get("name", data["id"]),
                "category": data.get("category", "misc"),
                "description": data.get("description", ""),
                "params": data.get("params", []),
            }
        )
    return out


def get_primitive(prim_id: str) -> dict | None:
    """Return the full primitive definition (including template) or None."""
    path = _catalog_dir() / f"{prim_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def _format_number(v: object) -> str:
    """Format numbers the way drawlang expects: no scientific notation, no
    trailing zeros, ints stay ints."""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        # keep 4 decimal places max, strip trailing zeros
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s or "0"
    return str(v)


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _resolve_defaults(prim: dict, values: dict) -> dict:
    """Merge caller-supplied ``values`` on top of the primitive's declared
    defaults. Unknown values are dropped."""
    resolved = {}
    for p in prim.get("params", []):
        name = p["name"]
        if name in values and values[name] is not None and values[name] != "":
            resolved[name] = _coerce(p.get("type", "text"), values[name])
        else:
            resolved[name] = _coerce(p.get("type", "text"), p.get("default"))
    return resolved


def _coerce(ptype: str, v):
    if v is None:
        return None
    if ptype == "number":
        try:
            f = float(v)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return 0
    if ptype == "boolean":
        return bool(v)
    return str(v)


def _pick_template(prim: dict, params: dict) -> str:
    """Return the drawlang template for these params.

    Primitives may declare either ``template`` (single string) or
    ``template_variants`` (map keyed by one of the param values).
    """
    if "template" in prim:
        return prim["template"]
    variants = prim.get("template_variants")
    if variants:
        # Find the first select param whose value matches a variant key.
        for p in prim.get("params", []):
            if p.get("type") == "select":
                val = params.get(p["name"])
                if val in variants:
                    return variants[val]
        # Fall back to the first variant
        return next(iter(variants.values()))
    raise ValueError(f"primitive {prim.get('id')!r} has no template")


def expand(prim: dict, values: dict) -> tuple[str, str]:
    """Expand ``prim`` with the given user ``values`` into drawlang.

    Returns ``(drawlang_text, meaning_tag)``.
    """
    resolved = _resolve_defaults(prim, values)

    # Evaluate the compute block, if any, in an env that starts as `resolved`.
    env = dict(resolved)
    for name, expr in (prim.get("compute") or {}).items():
        env[name] = _safe_eval(expr, env)

    template = _pick_template(prim, resolved)

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in env:
            raise ValueError(f"template references unknown param: {key}")
        return _format_number(env[key])

    drawlang = _PLACEHOLDER.sub(_replace, template).strip()

    # Meaning tag: `primitive:<id>{param=value,...}` — enough for the editor
    # to recover the original parametric intent from a raw drawlang stream.
    body = ",".join(f"{k}={_format_number(resolved[k])}" for k in resolved)
    tag = f"primitive:{prim['id']}{{{body}}}"

    return drawlang, tag
