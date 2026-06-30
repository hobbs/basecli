"""The view engine: filter -> sort -> group -> limit -> select -> summarize."""

from __future__ import annotations

import functools
from typing import Any, Dict, List, Optional, Tuple

from .base import Base, View
from .errors import EvalError, SchemaError
from .evaluator import Context, Env, evaluate
from .parser import parse_expression
from .values import (
    BDate, BDuration, compare, display_value, is_truthy, json_value,
    to_number, type_name, values_equal,
)
from .vault import Vault

# Extensible view-type registry. Built-in layouts all produce the *same*
# tabular row data (basecli is headless and JSON-first); ``--format`` controls
# the human rendering. The registry gates which ``view.type`` values are
# accepted — register a plugin layout by name to have it render as a table too.
VIEW_TYPES = {"table", "list", "cards", "map"}


def register_view_type(name: str) -> None:
    VIEW_TYPES.add(name)


def _check_view_type(view: View) -> None:
    if view.type not in VIEW_TYPES:
        raise SchemaError(
            f'Unknown view type "{view.type}". Built-in: {sorted(VIEW_TYPES)}. '
            f"Register plugin layouts with basecli.engine.register_view_type().",
            {"type": view.type, "known": sorted(VIEW_TYPES)},
        )


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def _passes(spec: Any, ctx: Context) -> bool:
    if spec is None:
        return True
    if isinstance(spec, bool):
        return spec
    if isinstance(spec, str):
        return is_truthy(evaluate(parse_expression(spec), ctx))
    if isinstance(spec, list):
        return all(_passes(s, ctx) for s in spec)
    if isinstance(spec, dict):
        ok = True
        for key, val in spec.items():
            items = val if isinstance(val, list) else [val]
            if key == "and":
                r = all(_passes(i, ctx) for i in items)
            elif key == "or":
                r = any(_passes(i, ctx) for i in items)
            elif key == "not":
                r = not any(_passes(i, ctx) for i in items)
            else:
                raise SchemaError(f'Unknown filter conjunction "{key}"')
            ok = ok and r
        return ok
    raise SchemaError(f"Invalid filter spec: {spec!r}")


# ---------------------------------------------------------------------------
# Row evaluation
# ---------------------------------------------------------------------------
class Row:
    __slots__ = ("file", "ctx", "cells", "group_value")

    def __init__(self, file, ctx, cells, group_value):
        self.file = file
        self.ctx = ctx
        self.cells = cells  # column_id -> raw value
        self.group_value = group_value


def _eval_property(prop: str, ctx: Context) -> Any:
    """Evaluate a column / sort / group property id as an expression."""
    try:
        return evaluate(parse_expression(prop), ctx)
    except EvalError:
        return None


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def _is_empty_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return len(v) == 0
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, dict):
        return len(v) == 0
    return False


def _numbers(values: List[Any]) -> List[float]:
    out = []
    for v in values:
        if isinstance(v, bool):
            continue
        n = to_number(v)
        if n is not None and not isinstance(v, BDate):
            out.append(n)
    return out


def _dates(values: List[Any]) -> List[BDate]:
    return [v for v in values if isinstance(v, BDate)]


def _builtin_summary(name: str, values: List[Any]) -> Any:
    key = name.lower()
    nums = _numbers(values)
    dates = _dates(values)

    if key == "average":
        return sum(nums) / len(nums) if nums else None
    if key == "sum":
        return sum(nums) if nums else 0
    if key == "min":
        return min(nums) if nums else None
    if key == "max":
        return max(nums) if nums else None
    if key == "median":
        s = sorted(nums)
        if not s:
            return None
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    if key == "stddev":
        if len(nums) < 2:
            return 0
        mean = sum(nums) / len(nums)
        return (sum((n - mean) ** 2 for n in nums) / len(nums)) ** 0.5
    if key == "range":
        if dates:
            return BDuration.from_timedelta(max(d.dt for d in dates) - min(d.dt for d in dates))
        return (max(nums) - min(nums)) if nums else None
    if key == "earliest":
        return BDate(min(d.dt for d in dates)) if dates else None
    if key == "latest":
        return BDate(max(d.dt for d in dates)) if dates else None
    if key == "checked":
        return sum(1 for v in values if v is True)
    if key == "unchecked":
        return sum(1 for v in values if v is False)
    if key == "empty":
        return sum(1 for v in values if _is_empty_value(v))
    if key == "filled":
        return sum(1 for v in values if not _is_empty_value(v))
    if key == "unique":
        uniq: List[Any] = []
        for v in values:
            if not any(values_equal(v, u) for u in uniq):
                uniq.append(v)
        return len(uniq)
    return None


_BUILTIN_SUMMARIES = {
    "average", "sum", "min", "max", "median", "stddev", "range", "earliest",
    "latest", "checked", "unchecked", "empty", "filled", "unique",
}


def _compute_summary(summary_name: str, prop: str, rows: List[Row], base: Base,
                     env: Env) -> Dict[str, Any]:
    values = [r.cells.get(prop) if prop in r.cells else _eval_property(prop, r.ctx)
              for r in rows]
    if summary_name.lower() in _BUILTIN_SUMMARIES:
        value = _builtin_summary(summary_name, values)
    elif summary_name in base.summaries:
        # Custom summary formula with `values` bound to the property's values.
        try:
            value = evaluate(base.summaries[summary_name], _SummaryContext(env, values))
        except EvalError:
            value = None
    else:
        raise SchemaError(f'Unknown summary "{summary_name}"')
    return {"name": summary_name, "value": json_value(value), "display": display_value(value)}


class _SummaryContext(Context):
    """Context where the bare/`values` identifier yields the summary value list."""

    def __init__(self, env: Env, values: List[Any]):
        super().__init__(env, file=None, note={"values": values})


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def run_view(base: Base, vault: Vault, view: View, *,
             today: BDate, now: BDate, this_obj: Any = None,
             limit_override: Optional[int] = None,
             columns_override: Optional[List[str]] = None,
             no_group: bool = False) -> Dict[str, Any]:
    _check_view_type(view)
    env = Env(vault=vault, today=today, now=now, formulas=base.formulas, this_obj=this_obj)

    # 1. Filter (global AND view).
    matched: List[Row] = []
    for bf in vault.files:
        ctx = Context(env, file=bf)
        if not _passes(base.global_filters, ctx):
            continue
        if not _passes(view.filters, ctx):
            continue
        matched.append(Row(bf, ctx, {}, None))

    # Determine columns.
    columns = columns_override if columns_override is not None else list(view.order)
    if not columns:
        columns = ["file.name"]

    # 2. Compute selected cells + group value for each matched row.
    group_prop = None if no_group else (view.group_by["property"] if view.group_by else None)
    for row in matched:
        for col in columns:
            row.cells[col] = _eval_property(col, row.ctx)
        if group_prop:
            row.group_value = _eval_property(group_prop, row.ctx)

    # 3. Sort rows by the view's sort spec (stable, multi-key).
    rows = _sort_rows(matched, view.sort)

    # 4. Apply limit across the flattened result (in group then row order).
    limit = limit_override if limit_override is not None else view.limit
    grouped = _group_rows(rows, group_prop, view.group_by, no_group)
    if limit is not None:
        grouped = _apply_limit(grouped, int(limit))

    # 5. Build output groups with cells + summaries.
    out_groups = []
    total = 0
    for gkey_value, grows in grouped:
        total += len(grows)
        out_rows = [_render_row(r, columns) for r in grows]
        summaries = {}
        for prop, sname in (view.summaries or {}).items():
            summaries[prop] = _compute_summary(sname, prop, grows, base, env)
        out_groups.append({
            "key": None if gkey_value is _NO_GROUP else display_value(gkey_value),
            "rows": out_rows,
            "summaries": summaries,
        })

    columns_meta = [{"id": c, "displayName": _display_name(base, c)} for c in columns]

    return {
        "base": _basename(base.source_path),
        "view": {"name": view.name, "type": view.type},
        "today": today.iso() if today else None,
        "columns": columns_meta,
        "groups": out_groups,
        "summaries": {},
        "row_count": total,
    }


_NO_GROUP = object()


def _sort_rows(rows: List[Row], sort_spec: List[Dict[str, str]]) -> List[Row]:
    if not sort_spec:
        return rows
    ordered = list(rows)
    # Apply sort keys from last to first for a stable multi-key sort.
    for spec in reversed(sort_spec):
        prop = spec["property"]
        direction = spec.get("direction", "ASC").upper()
        reverse = direction == "DESC"

        def key_cmp(a: Row, b: Row, _prop=prop):
            va = a.cells.get(_prop) if _prop in a.cells else _eval_property(_prop, a.ctx)
            vb = b.cells.get(_prop) if _prop in b.cells else _eval_property(_prop, b.ctx)
            return compare(va, vb)

        ordered.sort(key=functools.cmp_to_key(key_cmp), reverse=reverse)
    return ordered


def _group_rows(rows: List[Row], group_prop: Optional[str],
                group_by: Optional[Dict[str, str]], no_group: bool
                ) -> List[Tuple[Any, List[Row]]]:
    if not group_prop:
        return [(_NO_GROUP, rows)]

    # Preserve first-seen order of group keys (rows already in sort order).
    keys: List[Any] = []
    buckets: Dict[Any, List[Row]] = {}
    for row in rows:
        gv = row.group_value
        hk = _hash_key(gv)
        if hk not in buckets:
            buckets[hk] = []
            keys.append((hk, gv))
        buckets[hk].append(row)

    direction = (group_by or {}).get("direction", "ASC").upper()
    reverse = direction == "DESC"
    keys.sort(key=functools.cmp_to_key(lambda a, b: compare(a[1], b[1])), reverse=reverse)
    return [(gv, buckets[hk]) for hk, gv in keys]


def _hash_key(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        return display_value(value)


def _apply_limit(grouped: List[Tuple[Any, List[Row]]], limit: int
                 ) -> List[Tuple[Any, List[Row]]]:
    out = []
    remaining = limit
    for gkey, grows in grouped:
        if remaining <= 0:
            break
        take = grows[:remaining]
        remaining -= len(take)
        out.append((gkey, take))
    return out


def _render_row(row: Row, columns: List[str]) -> Dict[str, Any]:
    cells = {}
    for col in columns:
        v = row.cells.get(col)
        cells[col] = {"value": json_value(v), "display": display_value(v)}
    return {
        "file": {
            "path": row.file.path,
            "abspath": row.file.abspath,
            "name": row.file.name,
            "basename": row.file.basename,
        },
        "cells": cells,
    }


def _display_name(base: Base, col: str) -> str:
    prop = base.properties.get(col)
    if isinstance(prop, dict) and prop.get("displayName"):
        return prop["displayName"]
    return col


def _basename(path: str) -> str:
    import os
    return os.path.basename(path)


def list_views(base: Base, vault: Vault, *, today: BDate, now: BDate,
               this_obj: Any = None) -> List[Dict[str, Any]]:
    env = Env(vault=vault, today=today, now=now, formulas=base.formulas, this_obj=this_obj)
    out = []
    for view in base.views:
        count = 0
        for bf in vault.files:
            ctx = Context(env, file=bf)
            if _passes(base.global_filters, ctx) and _passes(view.filters, ctx):
                count += 1
        out.append({"name": view.name, "type": view.type, "row_count": count})
    return out
