"""Evaluate an AST against a row context.

Handles operators (with JS short-circuiting and date arithmetic), the
``note`` / ``file`` / ``formula`` / ``this`` roots, bare-name frontmatter
shorthand, the ``value`` / ``index`` / ``acc`` lambda bindings, and the lazy
special forms ``if`` / ``filter`` / ``map`` / ``reduce``.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from . import functions as fns
from .errors import EvalError
from .parser import (
    Binary, Call, Identifier, Index, ListLit, Literal, Member, Node,
    ObjectLit, RegexpLit, Unary, parse_expression,
)
from .values import (
    BDate, BDuration, BLink, BRegexp, compare, is_truthy, to_number,
    to_string, type_name, values_equal,
)

_ROOTS = {"note", "file", "formula", "this"}
_LAMBDA_VARS = {"value", "index", "acc"}


class Env:
    """Configuration shared across all rows of a base evaluation."""

    def __init__(self, vault, today: BDate, now: BDate,
                 formulas: Optional[Dict[str, Node]] = None,
                 this_obj: Any = None):
        self.vault = vault
        self.today = today
        self.now = now
        self.formulas = formulas or {}
        self.this_obj = this_obj


class FormulaNamespace:
    """The ``formula`` root. Member access computes the named formula lazily."""

    __slots__ = ("ctx",)

    def __init__(self, ctx):
        self.ctx = ctx

    def get(self, name: str) -> Any:
        return self.ctx.compute_formula(name)


class Context:
    """Per-row evaluation context."""

    def __init__(self, env: Env, file=None, note: Optional[Dict[str, Any]] = None,
                 extra: Optional[Dict[str, Any]] = None):
        self.env = env
        self.file = file
        self.note = note if note is not None else (dict(file.properties) if file else {})
        self.extra = extra or {}
        self._formula_cache: Dict[str, Any] = {}
        self._formula_computing: set = set()
        self._lambda_stack: List[Dict[str, Any]] = []

    # -- formulas -----------------------------------------------------------
    def compute_formula(self, name: str) -> Any:
        if name in self._formula_cache:
            return self._formula_cache[name]
        if name not in self.env.formulas:
            return None
        if name in self._formula_computing:
            raise EvalError(
                f'Circular reference in formula "{name}"',
                {"formula": name, "chain": list(self._formula_computing)},
            )
        self._formula_computing.add(name)
        try:
            value = evaluate(self.env.formulas[name], self)
        finally:
            self._formula_computing.discard(name)
        self._formula_cache[name] = value
        return value

    # -- file/link resolution ----------------------------------------------
    def resolve_file(self, value: Any):
        if value is None or self.env.vault is None:
            return None
        if getattr(value, "_is_bfile", False):
            return value
        if isinstance(value, BLink):
            return self.env.vault.resolve_link(value.target)
        if isinstance(value, str):
            v = self.env.vault.resolve_link(value)
            if v is not None:
                return v
            return self.env.vault.by_path.get(value)
        return None

    # -- lambda scope -------------------------------------------------------
    def push_lambda(self, bindings: Dict[str, Any]):
        self._lambda_stack.append(bindings)

    def pop_lambda(self):
        self._lambda_stack.pop()

    def lookup_lambda(self, name: str):
        for frame in reversed(self._lambda_stack):
            if name in frame:
                return True, frame[name]
        return False, None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(node: Node, ctx: Context) -> Any:
    t = type(node)

    if t is Literal:
        return node.value

    if t is RegexpLit:
        return BRegexp(node.pattern, node.flags)

    if t is Identifier:
        return _eval_identifier(node.name, ctx)

    if t is ListLit:
        return [evaluate(e, ctx) for e in node.elements]

    if t is ObjectLit:
        return {k: evaluate(v, ctx) for k, v in node.pairs}

    if t is Member:
        return _eval_member(node, ctx)

    if t is Index:
        return _eval_index(node, ctx)

    if t is Unary:
        return _eval_unary(node, ctx)

    if t is Binary:
        return _eval_binary(node, ctx)

    if t is Call:
        return _eval_call(node, ctx)

    raise EvalError(f"Cannot evaluate node {node!r}")


def _eval_identifier(name: str, ctx: Context) -> Any:
    if name in _LAMBDA_VARS:
        found, val = ctx.lookup_lambda(name)
        if found:
            return val
    if name == "note":
        return ctx.note
    if name == "file":
        return ctx.file
    if name == "formula":
        return FormulaNamespace(ctx)
    if name == "this":
        return ctx.env.this_obj
    # Bare-name shorthand: a frontmatter property.
    return ctx.note.get(name)


def _eval_member(node: Member, ctx: Context) -> Any:
    # `formula.x` needs the namespace, not a generic value.
    if isinstance(node.obj, Identifier) and node.obj.name == "formula" \
            and not _shadowed(ctx, "formula"):
        return ctx.compute_formula(node.name)
    obj = evaluate(node.obj, ctx)
    return _access(obj, node.name)


def _shadowed(ctx: Context, name: str) -> bool:
    found, _ = ctx.lookup_lambda(name)
    return found


def _access(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, FormulaNamespace):
        return obj.get(name)
    if isinstance(obj, dict):
        return obj.get(name)
    if getattr(obj, "_is_bfile", False):
        return _access_file_field(obj, name)
    if isinstance(obj, BDate):
        if name in ("year", "month", "day", "hour", "minute", "second", "millisecond"):
            return getattr(obj, name)
        raise EvalError(f'Cannot read property "{name}" on type Date')
    if isinstance(obj, str):
        if name == "length":
            return len(obj)
        raise EvalError(f'Cannot read property "{name}" on type String')
    if isinstance(obj, list):
        if name == "length":
            return len(obj)
        raise EvalError(f'Cannot read property "{name}" on type List')
    raise EvalError(f'Cannot read property "{name}" on type {fns._title_type(type_name(obj))}')


_FILE_FIELDS = {
    "name", "basename", "path", "folder", "ext", "size", "ctime", "mtime",
    "tags", "links", "embeds", "backlinks", "properties", "file",
}


def _access_file_field(bf, name: str) -> Any:
    if name in _FILE_FIELDS:
        return getattr(bf, name)
    # Allow access to arbitrary frontmatter via file as a fallback.
    if name in bf.properties:
        return bf.properties[name]
    raise EvalError(f'Cannot read property "{name}" on type File')


def _eval_index(node: Index, ctx: Context) -> Any:
    obj = evaluate(node.obj, ctx)
    idx = evaluate(node.index, ctx)
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(idx if isinstance(idx, str) else to_string(idx))
    if isinstance(obj, list):
        i = to_number(idx)
        if i is None:
            return None
        i = int(i)
        return obj[i] if -len(obj) <= i < len(obj) else None
    if isinstance(obj, str):
        i = to_number(idx)
        if i is None:
            return None
        i = int(i)
        return obj[i] if -len(obj) <= i < len(obj) else None
    if getattr(obj, "_is_bfile", False):
        return _access(obj.properties, to_string(idx))
    return None


def _eval_unary(node: Unary, ctx: Context) -> Any:
    if node.op == "!":
        return not is_truthy(evaluate(node.operand, ctx))
    if node.op == "-":
        n = to_number(evaluate(node.operand, ctx))
        return -n if n is not None else None
    raise EvalError(f"Unknown unary operator {node.op}")


def _eval_binary(node: Binary, ctx: Context) -> Any:
    op = node.op
    # Short-circuit logical operators (JS: return the operand, not a bool).
    if op == "&&":
        left = evaluate(node.left, ctx)
        if not is_truthy(left):
            return left
        return evaluate(node.right, ctx)
    if op == "||":
        left = evaluate(node.left, ctx)
        if is_truthy(left):
            return left
        return evaluate(node.right, ctx)

    left = evaluate(node.left, ctx)
    right = evaluate(node.right, ctx)

    if op == "==":
        return _eq(left, right)
    if op == "!=":
        return not _eq(left, right)
    if op in ("<", ">", "<=", ">="):
        return _compare_op(op, left, right)
    if op == "+":
        return _add(left, right)
    if op == "-":
        return _subtract(left, right)
    if op == "*":
        return _multiply(left, right)
    if op == "/":
        return _divide(left, right)
    if op == "%":
        return _modulo(left, right)
    raise EvalError(f"Unknown operator {op}")


def _coerce_date_pair(a: Any, b: Any):
    """If exactly one side is a Date and the other a date-like string, coerce."""
    if isinstance(a, BDate) and isinstance(b, str):
        d = BDate.parse(b)
        if d is not None:
            return a, d
    if isinstance(b, BDate) and isinstance(a, str):
        d = BDate.parse(a)
        if d is not None:
            return d, b
    return a, b


def _eq(a: Any, b: Any) -> bool:
    a, b = _coerce_date_pair(a, b)
    return values_equal(a, b)


def _compare_op(op: str, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    a, b = _coerce_date_pair(a, b)
    c = compare(a, b)
    if op == "<":
        return c < 0
    if op == ">":
        return c > 0
    if op == "<=":
        return c <= 0
    return c >= 0


def _as_duration(v: Any) -> Optional[BDuration]:
    if isinstance(v, BDuration):
        return v
    if isinstance(v, str):
        try:
            return BDuration.parse(v)
        except EvalError:
            return None
    return None


def _add(a: Any, b: Any) -> Any:
    # Date + duration / duration + Date
    if isinstance(a, BDate):
        d = _as_duration(b)
        if d is not None:
            return d.apply(a, +1)
    if isinstance(b, BDate):
        d = _as_duration(a)
        if d is not None:
            return d.apply(b, +1)
    # String concatenation (JS-style) when either side is a string.
    if isinstance(a, str) or isinstance(b, str):
        return to_string(a) + to_string(b)
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None:
        return None
    return na + nb


def _subtract(a: Any, b: Any) -> Any:
    if isinstance(a, BDate) and isinstance(b, BDate):
        td = a.dt - b.dt
        return BDuration.from_timedelta(td)
    if isinstance(a, BDate):
        d = _as_duration(b)
        if d is not None:
            return d.apply(a, -1)
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None:
        return None
    return na - nb


def _multiply(a: Any, b: Any) -> Any:
    if isinstance(a, BDuration):
        n = to_number(b)
        if n is not None:
            return a.scaled(n)
    if isinstance(b, BDuration):
        n = to_number(a)
        if n is not None:
            return b.scaled(n)
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None:
        return None
    return na * nb


def _divide(a: Any, b: Any) -> Any:
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None:
        return None
    if nb == 0:
        if na == 0:
            return float("nan")
        return float("inf") if na > 0 else float("-inf")
    return na / nb


def _modulo(a: Any, b: Any) -> Any:
    na, nb = to_number(a), to_number(b)
    if na is None or nb is None or nb == 0:
        return None
    return na % nb


# ---------------------------------------------------------------------------
# Calls (and the lazy special forms)
# ---------------------------------------------------------------------------
def _eval_call(node: Call, ctx: Context) -> Any:
    callee = node.callee

    if isinstance(callee, Member):
        name = callee.name
        if name in fns.LAZY_METHODS:
            return _eval_lazy_method(callee, node.args, ctx)
        recv = evaluate(callee.obj, ctx)
        args = [evaluate(a, ctx) for a in node.args]
        return fns.call_method(ctx, recv, name, args)

    if isinstance(callee, Identifier):
        name = callee.name
        if name == "if":
            return _eval_if(node.args, ctx)
        args = [evaluate(a, ctx) for a in node.args]
        return fns.call_global(ctx, name, args)

    raise EvalError("Expression is not callable")


def _eval_if(args: List[Node], ctx: Context) -> Any:
    if len(args) < 2:
        raise EvalError("if() requires at least a condition and a true branch")
    cond = evaluate(args[0], ctx)
    if is_truthy(cond):
        return evaluate(args[1], ctx)
    if len(args) >= 3:
        return evaluate(args[2], ctx)
    return None


def _eval_lazy_method(callee: Member, arg_nodes: List[Node], ctx: Context) -> Any:
    recv = evaluate(callee.obj, ctx)
    name = callee.name
    if not isinstance(recv, list):
        # Methods only apply to lists; surface the same dispatch error.
        raise EvalError(f'Cannot find function "{name}" on type {fns._title_type(type_name(recv))}')

    if name == "filter":
        body = arg_nodes[0]
        out = []
        for i, item in enumerate(recv):
            ctx.push_lambda({"value": item, "index": i})
            try:
                keep = is_truthy(evaluate(body, ctx))
            finally:
                ctx.pop_lambda()
            if keep:
                out.append(item)
        return out

    if name == "map":
        body = arg_nodes[0]
        out = []
        for i, item in enumerate(recv):
            ctx.push_lambda({"value": item, "index": i})
            try:
                out.append(evaluate(body, ctx))
            finally:
                ctx.pop_lambda()
        return out

    if name == "reduce":
        body = arg_nodes[0]
        acc = evaluate(arg_nodes[1], ctx) if len(arg_nodes) > 1 else None
        for i, item in enumerate(recv):
            ctx.push_lambda({"value": item, "index": i, "acc": acc})
            try:
                acc = evaluate(body, ctx)
            finally:
                ctx.pop_lambda()
        return acc

    raise EvalError(f"Unknown lazy method {name}")


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------
def eval_string(source: str, ctx: Context) -> Any:
    """Parse and evaluate a source string in one shot (used by filters/tests)."""
    return evaluate(parse_expression(source), ctx)
