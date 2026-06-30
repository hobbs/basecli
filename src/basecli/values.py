"""The Bases type model: wrapper classes, truthiness, coercion, formatting.

Bases values map onto Python natives where possible and onto thin wrapper
classes where the semantics differ:

==================  ===================================
Bases type          Python representation
==================  ===================================
String              ``str``
Number              ``int`` / ``float``
Boolean             ``bool``
Null / empty        ``None``
List                ``list``
Object              ``dict``
Date                :class:`BDate`
Duration            :class:`BDuration`
Link                :class:`BLink`
File                :class:`BFile` (defined in ``vault.py``)
Regexp              :class:`BRegexp`
HTML/Image/Icon     :class:`BHtml` / :class:`BImage` / :class:`BIcon`
==================  ===================================

Truthiness follows JavaScript: ``None``, ``False``, ``0``, ``""``, ``[]`` and
absent properties are falsy; everything else (including ``{}``, dates and
durations) is truthy.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import math
from typing import Any, List, Optional

from dateutil import parser as _dateparser
from dateutil.relativedelta import relativedelta

from .errors import EvalError


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------
class BDate:
    """A Bases Date.

    Wraps a naive :class:`datetime.datetime` which is *interpreted as UTC* for
    the purpose of :func:`to_number` (epoch milliseconds). ``has_time`` records
    whether the source carried a time component, which only affects display.
    """

    __slots__ = ("dt", "has_time")

    def __init__(self, dt: _dt.datetime, has_time: bool = False):
        self.dt = dt
        self.has_time = has_time

    # -- construction --------------------------------------------------------
    @classmethod
    def from_value(cls, value: Any) -> Optional["BDate"]:
        """Normalize a frontmatter/literal value into a BDate (or None)."""
        if value is None:
            return None
        if isinstance(value, BDate):
            return value
        if isinstance(value, _dt.datetime):
            has_time = not (value.hour == value.minute == value.second == value.microsecond == 0)
            return cls(value.replace(tzinfo=None), has_time=has_time)
        if isinstance(value, _dt.date):
            return cls(_dt.datetime(value.year, value.month, value.day), has_time=False)
        if isinstance(value, str):
            return cls.parse(value)
        return None

    @classmethod
    def parse(cls, text: str) -> Optional["BDate"]:
        text = text.strip()
        if not text:
            return None
        try:
            dt = _dateparser.parse(text)
        except (ValueError, OverflowError):
            return None
        if dt.tzinfo is not None:
            # Collapse to naive UTC so epoch math is timezone-free.
            dt = dt.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        has_time = bool(_HAS_TIME_HINT(text))
        return cls(dt, has_time=has_time)

    # -- fields --------------------------------------------------------------
    @property
    def year(self) -> int:
        return self.dt.year

    @property
    def month(self) -> int:
        return self.dt.month

    @property
    def day(self) -> int:
        return self.dt.day

    @property
    def hour(self) -> int:
        return self.dt.hour

    @property
    def minute(self) -> int:
        return self.dt.minute

    @property
    def second(self) -> int:
        return self.dt.second

    @property
    def millisecond(self) -> int:
        return self.dt.microsecond // 1000

    # -- helpers -------------------------------------------------------------
    def epoch_ms(self) -> int:
        return int(calendar.timegm(self.dt.timetuple()) * 1000 + self.dt.microsecond // 1000)

    def date_only(self) -> "BDate":
        return BDate(_dt.datetime(self.dt.year, self.dt.month, self.dt.day), has_time=False)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BDate) and self.dt == other.dt

    def __hash__(self) -> int:
        return hash(self.dt)

    def __lt__(self, other: "BDate") -> bool:
        return self.dt < other.dt

    def iso(self) -> str:
        if self.has_time:
            return self.dt.strftime("%Y-%m-%dT%H:%M:%S")
        return self.dt.strftime("%Y-%m-%d")

    def display(self) -> str:
        if self.has_time:
            return self.dt.strftime("%Y-%m-%d %H:%M:%S")
        return self.dt.strftime("%Y-%m-%d")

    def __repr__(self) -> str:
        return f"BDate({self.iso()!r})"


def _HAS_TIME_HINT(text: str) -> bool:
    """Heuristic: did the source string carry an explicit time component?"""
    return ":" in text or "T" in text


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------
_DURATION_UNITS = {
    "y": "years", "year": "years", "years": "years",
    "M": "months", "month": "months", "months": "months",
    "w": "weeks", "week": "weeks", "weeks": "weeks",
    "d": "day", "day": "day", "days": "day",
    "h": "hours", "hour": "hours", "hours": "hours",
    "m": "minutes", "minute": "minutes", "minutes": "minutes",
    "s": "seconds", "second": "seconds", "seconds": "seconds",
}

# relativedelta keyword for each canonical unit (note: singular for 'day').
_RD_KW = {
    "years": "years", "months": "months", "weeks": "weeks", "day": "days",
    "hours": "hours", "minutes": "minutes", "seconds": "seconds",
}

import re as _re

_DURATION_TOKEN = _re.compile(r"([+-]?\d+(?:\.\d+)?)\s*([A-Za-z]+)")


class BDuration:
    """A Bases Duration.

    Modeled as its own type with **no numeric methods**: calling e.g.
    ``.round()`` on it raises the same error Obsidian does. Durations from a
    string literal (``"1M"``) are calendar-relative; durations from
    ``date - date`` are absolute. Both can be applied to a :class:`BDate`.
    """

    __slots__ = ("components", "_timedelta")

    def __init__(self, components: Optional[dict] = None, timedelta: Optional[_dt.timedelta] = None):
        # Exactly one representation is used. ``components`` for calendar-based
        # (relativedelta) durations; ``_timedelta`` for absolute differences.
        self.components = components
        self._timedelta = timedelta

    @classmethod
    def parse(cls, text: str) -> "BDuration":
        comps: dict = {}
        matched = False
        for m in _DURATION_TOKEN.finditer(text):
            matched = True
            num = float(m.group(1))
            unit = m.group(2)
            if unit not in _DURATION_UNITS:
                raise EvalError(f'Unknown duration unit "{unit}" in "{text}"')
            canon = _DURATION_UNITS[unit]
            kw = _RD_KW[canon]
            comps[kw] = comps.get(kw, 0) + (int(num) if num.is_integer() else num)
        if not matched:
            raise EvalError(f'Cannot parse duration from "{text}"')
        return cls(components=comps)

    @classmethod
    def from_timedelta(cls, td: _dt.timedelta) -> "BDuration":
        return cls(timedelta=td)

    def _relativedelta(self) -> relativedelta:
        if self.components is not None:
            return relativedelta(**self.components)
        return relativedelta(seconds=self._timedelta.total_seconds())

    def apply(self, date: BDate, sign: int) -> BDate:
        if self.components is not None:
            rd = relativedelta(**self.components)
            new = date.dt + rd if sign > 0 else date.dt - rd
        else:
            new = date.dt + self._timedelta if sign > 0 else date.dt - self._timedelta
        return BDate(new, has_time=date.has_time or self._touches_time())

    def scaled(self, factor: float) -> "BDuration":
        if self.components is not None:
            return BDuration(components={k: v * factor for k, v in self.components.items()})
        return BDuration(timedelta=self._timedelta * factor)

    def _touches_time(self) -> bool:
        if self._timedelta is not None:
            return self._timedelta.seconds != 0 or self._timedelta.microseconds != 0
        return any(k in ("hours", "minutes", "seconds") for k in (self.components or {}))

    def display(self) -> str:
        if self._timedelta is not None:
            total = self._timedelta.total_seconds()
            return _humanize_seconds(total)
        parts = []
        order = [("years", "y"), ("months", "M"), ("weeks", "w"), ("days", "d"),
                 ("hours", "h"), ("minutes", "m"), ("seconds", "s")]
        for key, suffix in order:
            v = (self.components or {}).get(key)
            if v:
                parts.append(f"{v}{suffix}")
        return " ".join(parts) if parts else "0s"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, BDuration):
            return False
        return self.display() == other.display()

    def __hash__(self) -> int:
        return hash(self.display())

    def __repr__(self) -> str:
        return f"BDuration({self.display()!r})"


def _humanize_seconds(total: float) -> str:
    neg = total < 0
    total = abs(total)
    days = int(total // 86400)
    rem = total - days * 86400
    hours = int(rem // 3600)
    rem -= hours * 3600
    minutes = int(rem // 60)
    seconds = rem - minutes * 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds:g}s")
    body = " ".join(parts) if parts else "0s"
    return ("-" if neg else "") + body


# ---------------------------------------------------------------------------
# Link / Regexp / renderables
# ---------------------------------------------------------------------------
class BLink:
    """An internal or external link with optional display text."""

    __slots__ = ("target", "display_text", "is_external")

    def __init__(self, target: str, display_text: Any = None, is_external: bool = False):
        self.target = target
        self.display_text = display_text
        self.is_external = is_external

    def display(self) -> str:
        if self.display_text is not None and not isinstance(self.display_text, BLink):
            return display_value(self.display_text)
        return self.target

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, BLink):
            return _norm_link_target(self.target) == _norm_link_target(other.target)
        if isinstance(other, str):
            return _norm_link_target(self.target) == _norm_link_target(other)
        return False

    def __hash__(self) -> int:
        return hash(_norm_link_target(self.target))

    def __repr__(self) -> str:
        return f"BLink({self.target!r})"


def _norm_link_target(t: str) -> str:
    t = t.strip()
    if t.startswith("[[") and t.endswith("]]"):
        t = t[2:-2]
    if "|" in t:
        t = t.split("|", 1)[0]
    if "#" in t:
        t = t.split("#", 1)[0]
    return t.strip()


class BRegexp:
    __slots__ = ("pattern", "flags", "global_", "_re")

    def __init__(self, pattern: str, flags: str = ""):
        self.pattern = pattern
        self.flags = flags
        py_flags = 0
        if "i" in flags:
            py_flags |= _re.IGNORECASE
        if "s" in flags:
            py_flags |= _re.DOTALL
        if "m" in flags:
            py_flags |= _re.MULTILINE
        self.global_ = "g" in flags
        self._re = _re.compile(pattern, py_flags)

    def regex(self):
        return self._re

    def display(self) -> str:
        return f"/{self.pattern}/{self.flags}"

    def __repr__(self) -> str:
        return f"BRegexp(/{self.pattern}/{self.flags})"


class _Renderable:
    __slots__ = ("source",)

    def __init__(self, source: str):
        self.source = source

    def display(self) -> str:
        return self.source

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.source!r})"


class BHtml(_Renderable):
    pass


class BImage(_Renderable):
    pass


class BIcon(_Renderable):
    pass


# ---------------------------------------------------------------------------
# Truthiness, type names, coercion
# ---------------------------------------------------------------------------
def is_truthy(value: Any) -> bool:
    """JavaScript-style truthiness."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return False
        return value != 0
    if isinstance(value, str):
        return len(value) > 0
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        return True  # JS: any object (even {}) is truthy
    # BDate/BDuration/BLink/BFile/BRegexp/renderables are truthy when present.
    return True


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, BDate):
        return "date"
    if isinstance(value, BDuration):
        return "duration"
    if isinstance(value, BLink):
        return "link"
    if isinstance(value, BRegexp):
        return "regexp"
    if isinstance(value, (BHtml, BImage, BIcon)):
        return type(value).__name__.replace("B", "").lower()
    # BFile is defined in vault.py; identify structurally to avoid a cycle.
    if getattr(value, "_is_bfile", False):
        return "file"
    return "object"


def to_number(value: Any) -> Optional[float]:
    """Coerce to a number following Bases rules.

    Dates -> epoch milliseconds; booleans -> 0/1; numeric strings -> parsed
    number; everything non-coercible -> None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if any(c in s for c in ".eE") and not s.lstrip("+-").isdigit():
                return float(s)
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return None
    if isinstance(value, BDate):
        return value.epoch_ms()
    return None


def _fmt_number(n: float) -> str:
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if isinstance(n, float):
        if math.isnan(n):
            return "NaN"
        if math.isinf(n):
            return "Infinity" if n > 0 else "-Infinity"
        if n.is_integer():
            return str(int(n))
        return repr(n)
    return str(n)


def to_string(value: Any) -> str:
    """``any.toString()`` — string representation used by ``+`` concatenation."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _fmt_number(value)
    if isinstance(value, str):
        return value
    if isinstance(value, BDate):
        return value.display()
    if isinstance(value, BDuration):
        return value.display()
    if isinstance(value, BLink):
        return value.display()
    if isinstance(value, BRegexp):
        return value.display()
    if isinstance(value, (BHtml, BImage, BIcon)):
        return value.display()
    if isinstance(value, list):
        return ", ".join(to_string(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {to_string(v)}" for k, v in value.items())
    if getattr(value, "_is_bfile", False):
        return value.name
    return str(value)


def display_value(value: Any) -> str:
    """Human-facing rendering of a cell value (the ``display`` field)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _fmt_number(value)
    if isinstance(value, str):
        return value
    if isinstance(value, BDate):
        return value.display()
    if isinstance(value, BDuration):
        return value.display()
    if isinstance(value, BLink):
        return value.display()
    if isinstance(value, BRegexp):
        return value.display()
    if isinstance(value, (BHtml, BImage, BIcon)):
        return value.display()
    if isinstance(value, list):
        return ", ".join(display_value(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {display_value(v)}" for k, v in value.items())
    if getattr(value, "_is_bfile", False):
        return value.name
    return str(value)


def json_value(value: Any) -> Any:
    """JSON-serializable representation of the raw (typed) value."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, BDate):
        return value.iso()
    if isinstance(value, BDuration):
        return value.display()
    if isinstance(value, BLink):
        return value.target
    if isinstance(value, BRegexp):
        return value.display()
    if isinstance(value, (BHtml, BImage, BIcon)):
        return value.display()
    if isinstance(value, list):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if getattr(value, "_is_bfile", False):
        return value.path
    return to_string(value)


# ---------------------------------------------------------------------------
# Equality and ordering used by operators, filters and sort
# ---------------------------------------------------------------------------
def values_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        if isinstance(a, bool) and isinstance(b, bool):
            return a == b
        # bool vs number: compare numerically (JS-ish)
        na, nb = to_number(a), to_number(b)
        if na is not None and nb is not None:
            return na == nb
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, BDate) and isinstance(b, BDate):
        return a.dt == b.dt
    if isinstance(a, BLink) or isinstance(b, BLink):
        return _link_eq(a, b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, BDuration) and isinstance(b, BDuration):
        return a == b
    if type(a) is type(b):
        return a == b
    return False


def _link_eq(a: Any, b: Any) -> bool:
    if isinstance(a, BLink):
        return a == b
    if isinstance(b, BLink):
        return b == a
    return False


_ORDER_RANK = {
    "null": 0, "boolean": 1, "number": 2, "duration": 3, "date": 4,
    "string": 5, "link": 6, "list": 7, "object": 8, "file": 9,
}


def compare(a: Any, b: Any) -> int:
    """Three-way comparison for ``< > <= >=`` and sort.

    Returns -1/0/1. ``None`` sorts after everything else for ascending order
    (Obsidian pushes empty values to the end); within like types the natural
    order applies. Mixed incomparable types fall back to a stable type rank.
    """
    an, bn = a is None, b is None
    if an and bn:
        return 0
    if an:
        return 1  # None last
    if bn:
        return -1

    if isinstance(a, bool) and isinstance(b, bool):
        return (a > b) - (a < b)

    if isinstance(a, (int, float)) and not isinstance(a, bool) and \
       isinstance(b, (int, float)) and not isinstance(b, bool):
        return (a > b) - (a < b)

    if isinstance(a, BDate) and isinstance(b, BDate):
        return (a.dt > b.dt) - (a.dt < b.dt)

    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)

    if isinstance(a, BLink) and isinstance(b, BLink):
        ta, tb = _norm_link_target(a.target), _norm_link_target(b.target)
        return (ta > tb) - (ta < tb)

    if isinstance(a, BDuration) and isinstance(b, BDuration):
        sa = a._timedelta.total_seconds() if a._timedelta is not None else None
        sb = b._timedelta.total_seconds() if b._timedelta is not None else None
        if sa is not None and sb is not None:
            return (sa > sb) - (sa < sb)

    # Try numeric coercion for cross-type comparisons.
    na, nb = to_number(a), to_number(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)

    # Fall back to a stable rank so sort never raises.
    ra, rb = _ORDER_RANK.get(type_name(a), 99), _ORDER_RANK.get(type_name(b), 99)
    if ra != rb:
        return (ra > rb) - (ra < rb)
    sa, sb = to_string(a), to_string(b)
    return (sa > sb) - (sa < sb)
