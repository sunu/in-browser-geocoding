"""DAG schema: operator catalog, text form parser, slot substitution, and validator.

A DAG node is JSON: {"op": "<Operator>", "args": {"<name>": <node or literal>}}.
The text form in templates is: Filter(Children(${parent}, level=${level}), ${pred}).
Positional arguments map to the operator's argument names in catalog order.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# Value types
ENTITY, SET, GEOMETRY, LAYER, PREDICATE = "Entity", "Set", "Geometry", "Layer", "Predicate"
REGION = (ENTITY, SET, GEOMETRY)  # anything with a geometry
SETLIKE = (ENTITY, SET)
LINE = (LAYER, ENTITY, SET, GEOMETRY)


@dataclass(frozen=True)
class Arg:
    name: str
    types: tuple[str, ...]  # node output types, or "str"/"num" for literals
    required: bool = True
    choices_ref: str | None = None  # name of a closed option list


@dataclass(frozen=True)
class OpSpec:
    name: str
    args: tuple[Arg, ...]
    out: str
    doc: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _a(name, types, required=True, choices_ref=None):
    if isinstance(types, str):
        types = (types,)
    return Arg(name, tuple(types), required, choices_ref)


CATALOG: dict[str, OpSpec] = {s.name: s for s in [
    OpSpec("Resolve", (_a("name", "str"), _a("type_hint", "str", False), _a("context", "str", False),
                       _a("source", "str", False, "sources"), _a("id", "str", False)), ENTITY,
           "One named place. 'id' is set when the parser has resolved the name."),
    OpSpec("LexiconSet", (_a("key", "str", True, "lexicon"),), SET, "A named set from the lexicon."),
    OpSpec("Layer", (_a("name", "str", True, "layers"),), LAYER, "A spatial layer, for example the coastline."),
    OpSpec("Children", (_a("of", SETLIKE), _a("level", "str", True, "admin_levels")), SET),
    OpSpec("Parent", (_a("of", SETLIKE), _a("level", "str", True, "admin_levels")), ENTITY),
    OpSpec("Neighbors", (_a("of", SETLIKE), _a("level", "str", False, "admin_levels")), SET),
    OpSpec("Filter", (_a("set", SETLIKE), _a("pred", PREDICATE)), SET),
    OpSpec("Buffer", (_a("of", REGION), _a("distance_m", "num")), GEOMETRY),
    OpSpec("Centroid", (_a("of", REGION),), GEOMETRY),
    OpSpec("Direction", (_a("of", REGION), _a("dir", "str", True, "directions"),
                         _a("mode", "str", True, "direction_modes")), GEOMETRY),
    OpSpec("Union", (_a("a", REGION), _a("b", REGION)), SET),
    OpSpec("Intersect", (_a("a", REGION), _a("b", REGION)), SET),
    OpSpec("Difference", (_a("a", REGION), _a("b", REGION)), SET),
    OpSpec("Between", (_a("a", REGION), _a("b", REGION)), GEOMETRY),
    OpSpec("Along", (_a("line", LINE), _a("distance_m", "num"), _a("within", REGION, False)), GEOMETRY),
    OpSpec("Features", (_a("category", "str", True, "categories"), _a("within", REGION)), SET),
    OpSpec("AttrFilter", (_a("set", SETLIKE), _a("attr", "str", True, "attrs"), _a("op", "str", True, "ops"),
                          _a("value", "num")), SET),
    # Predicates
    OpSpec("Touches", (_a("target", LINE),), PREDICATE),
    OpSpec("Within", (_a("target", REGION),), PREDICATE),
    OpSpec("Intersects", (_a("target", REGION),), PREDICATE),
    OpSpec("WithinDistance", (_a("target", LINE), _a("distance_m", "num")), PREDICATE),
    OpSpec("Not", (_a("pred", PREDICATE),), PREDICATE),
]}

# Named predicate options (closed slot values) and their DAG form.
PREDICATE_DAGS: dict[str, dict[str, Any]] = {
    "coastal": {"op": "Touches", "args": {"target": {"op": "Layer", "args": {"name": "coastline"}}}},
    "landlocked": {"op": "Not", "args": {"pred": {"op": "Touches", "args": {"target": {"op": "Layer", "args": {"name": "coastline"}}}}}},
    "border": {"op": "Touches", "args": {"target": {"op": "Layer", "args": {"name": "country_boundary"}}}},
    "not_border": {"op": "Not", "args": {"pred": {"op": "Touches", "args": {"target": {"op": "Layer", "args": {"name": "country_boundary"}}}}}},
}

LAYERS = ["coastline", "country_boundary"]
DIRECTION_MODES = ["part", "outside"]
SOURCES = ["overture", "photon"]


# ---------------------------------------------------------------- text form parser

_TOKEN = re.compile(r"\s*(?:(\$\{[a-z_0-9]+\})|([A-Za-z_][A-Za-z_0-9]*)|(-?\d+(?:\.\d+)?)|(\"[^\"]*\"|'[^']*')|([(),=]))")


class DagSyntaxError(ValueError):
    pass


def _tokenize(s: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise DagSyntaxError(f"bad token at {pos}: {s[pos:pos + 20]!r}")
        pos = m.end()
        slot, ident, num, string, punct = m.groups()
        if slot:
            out.append(("slot", slot[2:-1]))
        elif ident:
            out.append(("ident", ident))
        elif num:
            out.append(("num", num))
        elif string:
            out.append(("str", string[1:-1]))
        else:
            out.append(("punct", punct))
    return out


def parse_dag_text(s: str) -> Any:
    """Parse the text form into JSON. Slots stay as {"$slot": name}."""
    toks = _tokenize(s)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else ("eof", "")

    def take(kind=None, val=None):
        nonlocal i
        t = peek()
        if (kind and t[0] != kind) or (val and t[1] != val):
            raise DagSyntaxError(f"expected {kind} {val}, got {t}")
        i += 1
        return t

    def value():
        k, v = peek()
        if k == "slot":
            take()
            return {"$slot": v}
        if k == "num":
            take()
            return float(v) if "." in v else int(v)
        if k == "str":
            take()
            return v
        if k == "ident":
            take()
            if peek() != ("punct", "("):
                return v  # bare word literal, for example level=state
            return call(v)
        raise DagSyntaxError(f"unexpected {peek()}")

    def call(op):
        if op not in CATALOG:
            raise DagSyntaxError(f"unknown operator {op}")
        spec = CATALOG[op]
        take("punct", "(")
        args: dict[str, Any] = {}
        pos = 0
        while peek() != ("punct", ")"):
            # keyword argument?
            if peek()[0] == "ident" and i + 1 < len(toks) and toks[i + 1] == ("punct", "="):
                name = take()[1]
                take("punct", "=")
                args[name] = value()
            else:
                if pos >= len(spec.args):
                    raise DagSyntaxError(f"too many positional args for {op}")
                args[spec.args[pos].name] = value()
                pos += 1
            if peek() == ("punct", ","):
                take()
        take("punct", ")")
        return {"op": op, "args": args}

    out = value()
    if i != len(toks):
        raise DagSyntaxError(f"trailing tokens: {toks[i:]}")
    return out


def substitute(node: Any, values: dict[str, Any]) -> Any:
    """Replace {"$slot": name} with values[name]. A None value removes the argument."""
    if isinstance(node, dict):
        if "$slot" in node:
            return values[node["$slot"]]
        out = {}
        for k, v in node.items():
            sv = substitute(v, values)
            if sv is None and k != "op":
                continue
            out[k] = sv
        if "args" in node and "args" not in out:
            out["args"] = {}
        return out
    if isinstance(node, list):
        return [substitute(v, values) for v in node]
    return node


# ---------------------------------------------------------------- validator


class DagValidationError(ValueError):
    pass


def output_type(node: Any) -> str:
    if isinstance(node, dict) and "op" in node:
        return CATALOG[node["op"]].out
    if isinstance(node, (int, float)):
        return "num"
    return "str"


def validate(node: Any, choices: dict[str, list[str]] | None = None, path: str = "$") -> list[str]:
    """Return a list of errors. An empty list means the DAG is valid."""
    errors: list[str] = []
    if not isinstance(node, dict) or "op" not in node:
        return [f"{path}: not an operator node"]
    op = node["op"]
    if op not in CATALOG:
        return [f"{path}: unknown operator {op}"]
    spec = CATALOG[op]
    args = node.get("args", {})
    known = {a.name for a in spec.args}
    for k in args:
        if k not in known:
            errors.append(f"{path}.{op}: unknown argument {k}")
    for a in spec.args:
        if a.name not in args:
            if a.required:
                errors.append(f"{path}.{op}: missing argument {a.name}")
            continue
        v = args[a.name]
        p = f"{path}.{op}.{a.name}"
        if isinstance(v, dict) and "$slot" in v:
            errors.append(f"{p}: unfilled slot {v['$slot']}")
            continue
        t = output_type(v)
        if t not in a.types:
            errors.append(f"{p}: type {t} is not one of {a.types}")
            continue
        if isinstance(v, dict):
            errors += validate(v, choices, p)
        elif choices and a.choices_ref and a.choices_ref in choices and v not in choices[a.choices_ref]:
            errors.append(f"{p}: value {v!r} is not in {a.choices_ref}")
    return errors


def depth(node: Any) -> int:
    """Number of nested Resolve-free operator levels. Used for reports only."""
    if not isinstance(node, dict) or "op" not in node:
        return 0
    return 1 + max((depth(v) for v in node.get("args", {}).values()), default=0)


def dumps(node: Any) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"))
