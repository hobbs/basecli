"""Load and validate a ``.base`` file; resolve formula dependency order."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import yaml

from .errors import SchemaError
from .parser import Call, Identifier, Index, ListLit, Member, Node, ObjectLit, \
    Unary, Binary, parse_expression

_BASE_BLOCK_RE = re.compile(r"```base[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


class View:
    def __init__(self, raw: Dict[str, Any], index: int):
        self.type = raw.get("type", "table")
        self.name = raw.get("name") or f"View {index + 1}"
        self.filters = raw.get("filters")
        self.group_by = _parse_group_by(raw.get("groupBy"))
        self.order: List[str] = list(raw.get("order") or [])
        self.sort = _parse_sort(raw.get("sort"))
        self.limit = raw.get("limit")
        self.summaries: Dict[str, str] = dict(raw.get("summaries") or {})
        self.raw = raw


def _parse_group_by(spec: Any) -> Optional[Dict[str, str]]:
    if not spec:
        return None
    if isinstance(spec, str):
        return {"property": spec, "direction": "ASC"}
    if isinstance(spec, dict):
        return {
            "property": spec.get("property"),
            "direction": (spec.get("direction") or "ASC").upper(),
        }
    raise SchemaError(f"Invalid groupBy: {spec!r}")


def _parse_sort(spec: Any) -> List[Dict[str, str]]:
    if not spec:
        return []
    out = []
    items = spec if isinstance(spec, list) else [spec]
    for item in items:
        if isinstance(item, str):
            out.append({"property": item, "direction": "ASC"})
        elif isinstance(item, dict):
            out.append({
                "property": item.get("property"),
                "direction": (item.get("direction") or "ASC").upper(),
            })
        else:
            raise SchemaError(f"Invalid sort entry: {item!r}")
    return out


class Base:
    def __init__(self, data: Dict[str, Any], source_path: str):
        if not isinstance(data, dict):
            raise SchemaError("Base file must be a YAML mapping")
        self.source_path = source_path
        self.global_filters = data.get("filters")
        self.properties: Dict[str, Any] = dict(data.get("properties") or {})

        # Compile formula and custom-summary expressions to ASTs.
        self.formula_sources: Dict[str, str] = {
            k: str(v) for k, v in (data.get("formulas") or {}).items()
        }
        self.formulas: Dict[str, Node] = {}
        for name, src in self.formula_sources.items():
            try:
                self.formulas[name] = parse_expression(src)
            except Exception as ex:  # noqa: BLE001 - re-wrap as schema error
                raise SchemaError(f'Failed to parse formula "{name}": {ex}',
                                  {"formula": name, "source": src})

        self.summary_sources: Dict[str, str] = {
            k: str(v) for k, v in (data.get("summaries") or {}).items()
        }
        self.summaries: Dict[str, Node] = {}
        for name, src in self.summary_sources.items():
            try:
                self.summaries[name] = parse_expression(src)
            except Exception as ex:  # noqa: BLE001
                raise SchemaError(f'Failed to parse summary "{name}": {ex}',
                                  {"summary": name, "source": src})

        # Topological pass over formula references — error on cycles up front.
        self.formula_order = _topo_sort_formulas(self.formulas)

        views_raw = data.get("views") or []
        if not isinstance(views_raw, list):
            raise SchemaError("`views` must be a list")
        self.views: List[View] = [View(v, i) for i, v in enumerate(views_raw)]

    def view_names(self) -> List[str]:
        return [v.name for v in self.views]

    def find_view(self, name: Optional[str]) -> View:
        if not self.views:
            raise SchemaError("Base defines no views")
        if name is None:
            return self.views[0]
        for v in self.views:
            if v.name == name:
                return v
        raise SchemaError(
            f'No view named "{name}"',
            {"available": self.view_names()},
        )


def _collect_formula_refs(node: Node, refs: set) -> None:
    """Find `formula.X` references anywhere in an AST."""
    if isinstance(node, Member):
        if isinstance(node.obj, Identifier) and node.obj.name == "formula":
            refs.add(node.name)
        else:
            _collect_formula_refs(node.obj, refs)
    elif isinstance(node, Index):
        _collect_formula_refs(node.obj, refs)
        _collect_formula_refs(node.index, refs)
    elif isinstance(node, Call):
        _collect_formula_refs(node.callee, refs)
        for a in node.args:
            _collect_formula_refs(a, refs)
    elif isinstance(node, Unary):
        _collect_formula_refs(node.operand, refs)
    elif isinstance(node, Binary):
        _collect_formula_refs(node.left, refs)
        _collect_formula_refs(node.right, refs)
    elif isinstance(node, ListLit):
        for e in node.elements:
            _collect_formula_refs(e, refs)
    elif isinstance(node, ObjectLit):
        for _, v in node.pairs:
            _collect_formula_refs(v, refs)


def _topo_sort_formulas(formulas: Dict[str, Node]) -> List[str]:
    deps: Dict[str, set] = {}
    for name, ast in formulas.items():
        refs: set = set()
        _collect_formula_refs(ast, refs)
        deps[name] = {r for r in refs if r in formulas}

    order: List[str] = []
    state: Dict[str, int] = {}  # 0=visiting, 1=done

    def visit(name: str, stack: List[str]):
        s = state.get(name)
        if s == 1:
            return
        if s == 0:
            cycle = stack[stack.index(name):] + [name]
            raise SchemaError(
                "Circular reference in formulas: " + " -> ".join(cycle),
                {"cycle": cycle},
            )
        state[name] = 0
        for dep in deps[name]:
            visit(dep, stack + [name])
        state[name] = 1
        order.append(name)

    for name in formulas:
        visit(name, [])
    return order


def load_base(path: str, embedded: bool = False) -> Base:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if embedded:
        m = _BASE_BLOCK_RE.search(text)
        if not m:
            raise SchemaError("No ```base code block found in file")
        text = m.group(1)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as ex:
        raise SchemaError(f"Invalid YAML in base file: {ex}")
    return Base(data or {}, source_path=path)
