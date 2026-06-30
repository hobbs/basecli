"""The Bases function registry.

One implementation per documented function, registered by ``(type, name)`` for
type methods and by ``name`` for globals. The registry is extensible: call
:func:`global_fn` / :func:`method` (or :func:`register_*`) to add functions, and
:func:`register_view_type` (in ``engine``) for view types.

Lazy/short-circuiting forms — ``if`` and the ``filter``/``map``/``reduce``
lambdas — are *not* here; they are special forms in :mod:`basecli.evaluator`
because they must receive unevaluated argument ASTs.
"""

from __future__ import annotations

import functools
import html as _htmlmod
import math
import random as _random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import EvalError
from .values import (
    BDate, BDuration, BHtml, BIcon, BImage, BLink, BRegexp,
    compare, display_value, is_truthy, to_number, to_string, type_name,
    values_equal,
)

# Registries -----------------------------------------------------------------
GLOBALS: Dict[str, Callable] = {}
METHODS: Dict[Tuple[str, str], Callable] = {}
ANY_METHODS: Dict[str, Callable] = {}

# Special forms known to the evaluator (documented here for discoverability).
LAZY_GLOBALS = {"if"}
LAZY_METHODS = {"filter", "map", "reduce"}


def global_fn(*names: str):
    def deco(f):
        for n in names:
            GLOBALS[n] = f
        return f
    return deco


def method(type_str: str, *names: str):
    def deco(f):
        for n in names:
            METHODS[(type_str, n)] = f
        return f
    return deco


def any_method(*names: str):
    def deco(f):
        for n in names:
            ANY_METHODS[n] = f
        return f
    return deco


def _title_type(tn: str) -> str:
    return {"regexp": "Regexp"}.get(tn, tn[:1].upper() + tn[1:])


def call_method(ctx, recv: Any, name: str, args: List[Any]) -> Any:
    tn = type_name(recv)
    fn = METHODS.get((tn, name))
    if fn is not None:
        return fn(ctx, recv, args)
    fn = ANY_METHODS.get(name)
    if fn is not None:
        return fn(ctx, recv, args)
    raise EvalError(f'Cannot find function "{name}" on type {_title_type(tn)}')


def call_global(ctx, name: str, args: List[Any]) -> Any:
    fn = GLOBALS.get(name)
    if fn is None:
        raise EvalError(f'Cannot find function "{name}"')
    return fn(ctx, args)


def _arg(args: List[Any], i: int, default=None):
    return args[i] if i < len(args) else default


# ---------------------------------------------------------------------------
# Global functions
# ---------------------------------------------------------------------------
@global_fn("escapeHTML")
def _g_escapeHTML(ctx, args):
    return _htmlmod.escape(to_string(_arg(args, 0)), quote=True)


@global_fn("date")
def _g_date(ctx, args):
    v = _arg(args, 0)
    if isinstance(v, BDate):
        return v
    return BDate.from_value(v if isinstance(v, str) else to_string(v))


@global_fn("duration")
def _g_duration(ctx, args):
    v = _arg(args, 0)
    if isinstance(v, BDuration):
        return v
    return BDuration.parse(to_string(v))


@global_fn("file")
def _g_file(ctx, args):
    v = _arg(args, 0)
    return ctx.resolve_file(v)


@global_fn("html")
def _g_html(ctx, args):
    return BHtml(to_string(_arg(args, 0)))


@global_fn("image")
def _g_image(ctx, args):
    return BImage(to_string(_arg(args, 0)))


@global_fn("icon")
def _g_icon(ctx, args):
    return BIcon(to_string(_arg(args, 0)))


@global_fn("link")
def _g_link(ctx, args):
    target = _arg(args, 0)
    display = _arg(args, 1)
    if getattr(target, "_is_bfile", False):
        return BLink(target.path, display_text=display)
    if isinstance(target, BLink):
        return BLink(target.target, display_text=display if display is not None else target.display_text,
                     is_external=target.is_external)
    s = to_string(target)
    is_ext = "://" in s
    return BLink(s, display_text=display, is_external=is_ext)


@global_fn("list")
def _g_list(ctx, args):
    v = _arg(args, 0)
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


@global_fn("max")
def _g_max(ctx, args):
    nums = _collect_numbers(args)
    return max(nums) if nums else None


@global_fn("min")
def _g_min(ctx, args):
    nums = _collect_numbers(args)
    return min(nums) if nums else None


def _collect_numbers(args):
    items = args
    if len(args) == 1 and isinstance(args[0], list):
        items = args[0]
    out = []
    for x in items:
        n = to_number(x)
        if n is not None:
            out.append(n)
    return out


@global_fn("now")
def _g_now(ctx, args):
    return ctx.env.now


@global_fn("today")
def _g_today(ctx, args):
    return ctx.env.today


@global_fn("number")
def _g_number(ctx, args):
    return to_number(_arg(args, 0))


@global_fn("random")
def _g_random(ctx, args):
    return _random.random()


# ---------------------------------------------------------------------------
# Any-type methods
# ---------------------------------------------------------------------------
@any_method("isTruthy")
def _a_isTruthy(ctx, recv, args):
    return is_truthy(recv)


@any_method("isType")
def _a_isType(ctx, recv, args):
    return type_name(recv) == to_string(_arg(args, 0))


@any_method("toString")
def _a_toString(ctx, recv, args):
    return to_string(recv)


@any_method("isEmpty")
def _a_isEmpty(ctx, recv, args):
    # Fallback for types without a specific isEmpty (notably null). Date,
    # String, Number, List, Object register their own and take precedence.
    if recv is None:
        return True
    if isinstance(recv, (str, list, dict)):
        return len(recv) == 0
    return False


# ---------------------------------------------------------------------------
# Date methods
# ---------------------------------------------------------------------------
@method("date", "date")
def _d_date(ctx, recv, args):
    return recv.date_only()


@method("date", "format")
def _d_format(ctx, recv, args):
    fmt = to_string(_arg(args, 0, "YYYY-MM-DD"))
    return moment_format(recv.dt, fmt)


@method("date", "time")
def _d_time(ctx, recv, args):
    return recv.dt.strftime("%H:%M:%S")


@method("date", "relative")
def _d_relative(ctx, recv, args):
    return relative_time(recv, ctx.env.now)


@method("date", "isEmpty")
def _d_isEmpty(ctx, recv, args):
    # Documented quirk: a Date is never "empty".
    return False


# ---------------------------------------------------------------------------
# String methods
# ---------------------------------------------------------------------------
@method("string", "contains")
def _s_contains(ctx, recv, args):
    return to_string(_arg(args, 0)) in recv


@method("string", "containsAll")
def _s_containsAll(ctx, recv, args):
    return all(to_string(a) in recv for a in args)


@method("string", "containsAny")
def _s_containsAny(ctx, recv, args):
    return any(to_string(a) in recv for a in args)


@method("string", "endsWith")
def _s_endsWith(ctx, recv, args):
    return recv.endswith(to_string(_arg(args, 0)))


@method("string", "startsWith")
def _s_startsWith(ctx, recv, args):
    return recv.startswith(to_string(_arg(args, 0)))


@method("string", "isEmpty")
def _s_isEmpty(ctx, recv, args):
    return len(recv) == 0


@method("string", "lower")
def _s_lower(ctx, recv, args):
    return recv.lower()


@method("string", "upper")
def _s_upper(ctx, recv, args):
    return recv.upper()


@method("string", "replace")
def _s_replace(ctx, recv, args):
    pattern = _arg(args, 0)
    replacement = to_string(_arg(args, 1, ""))
    if isinstance(pattern, BRegexp):
        repl = _convert_dollar_refs(replacement)
        count = 0 if pattern.global_ else 1
        return pattern.regex().sub(repl, recv, count=count)
    return recv.replace(to_string(pattern), replacement)


def _convert_dollar_refs(repl: str) -> str:
    # $1 -> \1, $$ -> $, leave \ alone but escape for re.sub.
    out = []
    i = 0
    while i < len(repl):
        c = repl[i]
        if c == "$" and i + 1 < len(repl):
            nxt = repl[i + 1]
            if nxt == "$":
                out.append("$")
                i += 2
                continue
            if nxt.isdigit():
                out.append("\\" + nxt)
                i += 2
                continue
        if c == "\\":
            out.append("\\\\")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


@method("string", "repeat")
def _s_repeat(ctx, recv, args):
    n = to_number(_arg(args, 0, 0)) or 0
    return recv * int(n)


@method("string", "reverse")
def _s_reverse(ctx, recv, args):
    return recv[::-1]


@method("string", "slice")
def _s_slice(ctx, recv, args):
    start = _int_or_none(_arg(args, 0))
    end = _int_or_none(_arg(args, 1)) if len(args) > 1 else None
    return recv[start:end]


@method("string", "split")
def _s_split(ctx, recv, args):
    sep = _arg(args, 0)
    n = _int_or_none(_arg(args, 1)) if len(args) > 1 else None
    if isinstance(sep, BRegexp):
        parts = sep.regex().split(recv)
    else:
        parts = recv.split(to_string(sep))
    if n is not None:
        parts = parts[:n]
    return parts


@method("string", "title")
def _s_title(ctx, recv, args):
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), recv.lower())


@method("string", "trim")
def _s_trim(ctx, recv, args):
    return recv.strip()


# ---------------------------------------------------------------------------
# Number methods
# ---------------------------------------------------------------------------
@method("number", "abs")
def _n_abs(ctx, recv, args):
    return abs(recv)


@method("number", "ceil")
def _n_ceil(ctx, recv, args):
    return math.ceil(recv)


@method("number", "floor")
def _n_floor(ctx, recv, args):
    return math.floor(recv)


@method("number", "round")
def _n_round(ctx, recv, args):
    digits = _int_or_none(_arg(args, 0)) if args else None
    return _round_half_up(recv, digits)


@method("number", "toFixed")
def _n_toFixed(ctx, recv, args):
    precision = _int_or_none(_arg(args, 0, 0)) or 0
    return f"{float(recv):.{precision}f}"


@method("number", "isEmpty")
def _n_isEmpty(ctx, recv, args):
    return False


def _round_half_up(x: float, digits: Optional[int]) -> Any:
    factor = 10 ** (digits or 0)
    # Half-up toward +inf (matches JS Math.round semantics).
    result = math.floor(x * factor + 0.5) / factor
    if digits is None or digits == 0:
        return int(result)
    return result


def _int_or_none(v):
    if v is None:
        return None
    n = to_number(v)
    return int(n) if n is not None else None


# ---------------------------------------------------------------------------
# List methods
# ---------------------------------------------------------------------------
@method("list", "contains")
def _l_contains(ctx, recv, args):
    target = _arg(args, 0)
    return any(values_equal(x, target) for x in recv)


@method("list", "containsAll")
def _l_containsAll(ctx, recv, args):
    return all(any(values_equal(x, a) for x in recv) for a in args)


@method("list", "containsAny")
def _l_containsAny(ctx, recv, args):
    return any(any(values_equal(x, a) for x in recv) for a in args)


@method("list", "flat")
def _l_flat(ctx, recv, args):
    out = []
    for x in recv:
        if isinstance(x, list):
            out.extend(x)
        else:
            out.append(x)
    return out


@method("list", "isEmpty")
def _l_isEmpty(ctx, recv, args):
    return len(recv) == 0


@method("list", "join")
def _l_join(ctx, recv, args):
    sep = to_string(_arg(args, 0, ""))
    return sep.join(to_string(x) for x in recv)


@method("list", "reverse")
def _l_reverse(ctx, recv, args):
    return list(reversed(recv))


@method("list", "slice")
def _l_slice(ctx, recv, args):
    start = _int_or_none(_arg(args, 0))
    end = _int_or_none(_arg(args, 1)) if len(args) > 1 else None
    return recv[start:end]


@method("list", "sort")
def _l_sort(ctx, recv, args):
    return sorted(recv, key=functools.cmp_to_key(compare))


@method("list", "unique")
def _l_unique(ctx, recv, args):
    out = []
    for x in recv:
        if not any(values_equal(x, y) for y in out):
            out.append(x)
    return out


# List aggregation methods. Not in the published function table, but the
# documented custom-summary example uses `values.mean()`, so summaries need
# them. (Flagged in README as an undocumented-but-required extension.)
@method("list", "sum")
def _l_sum(ctx, recv, args):
    nums = [to_number(x) for x in recv]
    nums = [n for n in nums if n is not None]
    return sum(nums) if nums else 0


@method("list", "average", "mean")
def _l_average(ctx, recv, args):
    nums = [to_number(x) for x in recv]
    nums = [n for n in nums if n is not None]
    return sum(nums) / len(nums) if nums else None


@method("list", "min")
def _l_min(ctx, recv, args):
    vals = [x for x in recv if x is not None]
    return min(vals, key=functools.cmp_to_key(compare)) if vals else None


@method("list", "max")
def _l_max(ctx, recv, args):
    vals = [x for x in recv if x is not None]
    return max(vals, key=functools.cmp_to_key(compare)) if vals else None


@method("list", "median")
def _l_median(ctx, recv, args):
    nums = sorted(n for n in (to_number(x) for x in recv) if n is not None)
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2


@method("list", "stddev")
def _l_stddev(ctx, recv, args):
    nums = [n for n in (to_number(x) for x in recv) if n is not None]
    if len(nums) < 2:
        return 0
    mean = sum(nums) / len(nums)
    var = sum((n - mean) ** 2 for n in nums) / len(nums)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# Link methods
# ---------------------------------------------------------------------------
@method("link", "asFile")
def _lk_asFile(ctx, recv, args):
    return ctx.resolve_file(recv)


@method("link", "linksTo")
def _lk_linksTo(ctx, recv, args):
    other = _arg(args, 0)
    resolved = ctx.resolve_file(recv)
    if resolved is None:
        return False
    if getattr(other, "_is_bfile", False):
        return resolved.path == other.path
    target = ctx.resolve_file(other)
    return target is not None and resolved.path == target.path


# ---------------------------------------------------------------------------
# File methods (delegate to BFile)
# ---------------------------------------------------------------------------
@method("file", "hasTag")
def _f_hasTag(ctx, recv, args):
    return recv.hasTag(*[to_string(a) for a in args])


@method("file", "inFolder")
def _f_inFolder(ctx, recv, args):
    return recv.inFolder(to_string(_arg(args, 0, "")))


@method("file", "hasProperty")
def _f_hasProperty(ctx, recv, args):
    return recv.hasProperty(to_string(_arg(args, 0)))


@method("file", "hasLink")
def _f_hasLink(ctx, recv, args):
    return recv.hasLink(_arg(args, 0))


@method("file", "asLink")
def _f_asLink(ctx, recv, args):
    return recv.asLink(_arg(args, 0) if args else None)


# ---------------------------------------------------------------------------
# Object methods
# ---------------------------------------------------------------------------
@method("object", "isEmpty")
def _o_isEmpty(ctx, recv, args):
    return len(recv) == 0


@method("object", "keys")
def _o_keys(ctx, recv, args):
    return list(recv.keys())


@method("object", "values")
def _o_values(ctx, recv, args):
    return list(recv.values())


# ---------------------------------------------------------------------------
# Regexp methods
# ---------------------------------------------------------------------------
@method("regexp", "matches")
def _r_matches(ctx, recv, args):
    return bool(recv.regex().search(to_string(_arg(args, 0))))


# ===========================================================================
# Moment.js-style date formatting
# ===========================================================================
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# Tokens longest-first so e.g. "YYYY" is matched before "YY".
def _build_moment_tokens(dt):
    h12 = dt.hour % 12 or 12
    return [
        ("YYYY", f"{dt.year:04d}"),
        ("YY", f"{dt.year % 100:02d}"),
        ("MMMM", _MONTHS[dt.month - 1]),
        ("MMM", _MONTHS[dt.month - 1][:3]),
        ("MM", f"{dt.month:02d}"),
        ("Mo", _ordinal(dt.month)),
        ("M", str(dt.month)),
        ("DD", f"{dt.day:02d}"),
        ("Do", _ordinal(dt.day)),
        ("D", str(dt.day)),
        ("dddd", _WEEKDAYS[dt.weekday()]),
        ("ddd", _WEEKDAYS[dt.weekday()][:3]),
        ("HH", f"{dt.hour:02d}"),
        ("H", str(dt.hour)),
        ("hh", f"{h12:02d}"),
        ("h", str(h12)),
        ("mm", f"{dt.minute:02d}"),
        ("m", str(dt.minute)),
        ("ss", f"{dt.second:02d}"),
        ("s", str(dt.second)),
        ("SSS", f"{dt.microsecond // 1000:03d}"),
        ("A", "AM" if dt.hour < 12 else "PM"),
        ("a", "am" if dt.hour < 12 else "pm"),
        ("X", str(int(dt.timestamp()) if dt.tzinfo else _epoch_naive(dt))),
    ]


def _epoch_naive(dt):
    import calendar
    return calendar.timegm(dt.timetuple())


def moment_format(dt, fmt: str) -> str:
    tokens = _build_moment_tokens(dt)
    out = []
    i = 0
    n = len(fmt)
    while i < n:
        c = fmt[i]
        if c == "[":
            j = fmt.find("]", i + 1)
            if j != -1:
                out.append(fmt[i + 1:j])
                i = j + 1
                continue
        matched = False
        for tok, val in tokens:
            if fmt.startswith(tok, i):
                out.append(val)
                i += len(tok)
                matched = True
                break
        if not matched:
            out.append(c)
            i += 1
    return "".join(out)


def relative_time(date: BDate, now: BDate) -> str:
    delta = date.epoch_ms() - now.epoch_ms()
    future = delta > 0
    secs = abs(delta) / 1000.0
    units = [
        (60, "second", "seconds"),
        (60, "minute", "minutes"),
        (24, "hour", "hours"),
        (30, "day", "days"),
        (12, "month", "months"),
        (None, "year", "years"),
    ]
    value = secs
    name_s, name_p = "second", "seconds"
    for factor, sing, plur in units:
        if factor is None or value < factor:
            name_s, name_p = sing, plur
            break
        value = value / factor
        name_s, name_p = sing, plur
    v = int(round(value))
    label = name_s if v == 1 else name_p
    if v == 0:
        return "now"
    return f"in {v} {label}" if future else f"{v} {label} ago"
