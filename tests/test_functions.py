"""Table-driven function & operator tests seeded from the Bases docs.

Every example on https://obsidian.md/help/bases/functions (and the operator
examples from the syntax page) is reproduced here verbatim as a fixture: the
doc's stated output is the expected value.
"""

import math

import pytest

from conftest import ev, evj

# (expression, expected JSON-serializable value) straight from the docs.
DOC_EXAMPLES = [
    # -- Global --------------------------------------------------------------
    ('number("3.4")', 3.4),
    ('list("value")', ["value"]),
    ('if(1, "yes", "no")', "yes"),
    ('if(0, "yes", "no")', "no"),
    ('if(0, "yes")', None),
    ("max(1, 5, 3)", 5),
    ("min(1, 5, 3)", 1),
    ('escapeHTML("<b>")', "&lt;b&gt;"),

    # -- Any -----------------------------------------------------------------
    ("1.isTruthy()", True),
    ("0.isTruthy()", False),
    ('"".isTruthy()', False),
    ('"example".isType("string")', True),
    ("123.isType(\"number\")", True),
    ("123.toString()", "123"),

    # -- String --------------------------------------------------------------
    ('"hello".contains("ell")', True),
    ('"hello".containsAll("h", "e")', True),
    ('"hello".containsAny("x", "y", "e")', True),
    ('"hello".endsWith("lo")', True),
    ('"hello".startsWith("he")', True),
    ('"".isEmpty()', True),
    ('"Hello world".isEmpty()', False),
    ('"a:b:c:d".replace(/:/, "-")', "a-b:c:d"),
    ('"a:b:c:d".replace(/:/g, "-")', "a-b-c-d"),
    (r'"John Smith".replace(/(\w+) (\w+)/, "$2, $1")', "Smith, John"),
    ('"123".repeat(2)', "123123"),
    ('"hello".reverse()', "olleh"),
    ('"hello".slice(1, 4)', "ell"),
    ('"a,b,c,d".split(",", 3)', ["a", "b", "c"]),
    ('"hello world".title()', "Hello World"),
    ('" hi ".trim()', "hi"),

    # -- Number --------------------------------------------------------------
    ("(-5).abs()", 5),
    ("(2.1).ceil()", 3),
    ("(2.9).floor()", 2),
    ("5.isEmpty()", False),
    ("(2.5).round()", 3),
    ("(2.3333).round(2)", 2.33),
    ("(3.14159).toFixed(2)", "3.14"),

    # -- List ----------------------------------------------------------------
    ("[1,2,3].contains(2)", True),
    ("[1,2,3].containsAll(2,3)", True),
    ("[1,2,3].containsAny(3,4)", True),
    ("[1,2,3,4].filter(value > 2)", [3, 4]),
    ("[1,[2,3]].flat()", [1, 2, 3]),
    ("[1,2,3].isEmpty()", False),
    ('[1,2,3].join(",")', "1,2,3"),
    ("[1,2,3,4].map(value + 1)", [2, 3, 4, 5]),
    ("[1,2,3].reduce(acc + value, 0)", 6),
    ("[1,2,3].reverse()", [3, 2, 1]),
    ("[1,2,3,4].slice(1,3)", [2, 3]),
    ("[3, 1, 2].sort()", [1, 2, 3]),
    ('["c", "a", "b"].sort()', ["a", "b", "c"]),
    ("[1,2,2,3].unique()", [1, 2, 3]),

    # -- Object --------------------------------------------------------------
    ("{}.isEmpty()", True),
    ('{a: 1, b: 2}.keys()', ["a", "b"]),
    ('{a: 1, b: 2}.values()', [1, 2]),

    # -- Regexp --------------------------------------------------------------
    ('/abc/.matches("abcde")', True),

    # -- Operators -----------------------------------------------------------
    ("1 + 2", 3),
    ("10 - 3", 7),
    ("4 * 5", 20),
    ("9 / 2", 4.5),
    ("9 % 2", 1),
    ("(2 + 3) * 4", 20),
    ("5 > 3", True),
    ("5 < 3", False),
    ("5 >= 5", True),
    ("5 <= 4", False),
    ("5 == 5", True),
    ("5 != 4", True),
    ("!true", False),
    ("!false", True),
    ("true && false", False),
    ("true || false", True),
    ('"a" + "b"', "ab"),
    ('"$" + 5', "$5"),
]


@pytest.mark.parametrize("expr,expected", DOC_EXAMPLES, ids=[e[0] for e in DOC_EXAMPLES])
def test_doc_example(expr, expected):
    assert evj(expr) == expected


# The reduce example with the pipe operator from the functions page (returns the
# largest number, or null). Confirms `|` is accepted as OR and lambda `acc`.
def test_reduce_max_example():
    note = {"values": [1, 4, 2, "x", 3]}
    expr = ('values.filter(value.isType("number"))'
            '.reduce(if(acc == null | value > acc, value, acc), null)')
    assert evj(expr, note) == 4


# -- Truthiness edge cases (JS semantics) ------------------------------------
TRUTHY = ["1", '"a"', "[1]", "true", "{}", "-1", "3.14"]
FALSY = ["0", '""', "[]", "false", "null"]


@pytest.mark.parametrize("expr", TRUTHY)
def test_truthy(expr):
    assert ev(f"if({expr}, true, false)") is True


@pytest.mark.parametrize("expr", FALSY)
def test_falsy(expr):
    assert ev(f"if({expr}, true, false)") is False


# -- Date fields and formatting ----------------------------------------------
def test_date_fields():
    assert ev('date("2026-04-27").year') == 2026
    assert ev('date("2026-04-27").month') == 4
    assert ev('date("2026-04-27").day') == 27


def test_date_format_moment_tokens():
    assert ev('date("2026-05-27").format("YYYY-MM-DD")') == "2026-05-27"
    assert ev('date("2026-05-27 13:05:09").format("YYYY-MM-DD HH:mm:ss")') == "2026-05-27 13:05:09"


def test_date_arithmetic_with_duration():
    # date + "7d" lands 7 days later.
    assert ev('date("2026-06-30") + "7d"').iso() == "2026-07-07"
    assert ev('date("2026-06-30") - "1d"').iso() == "2026-06-29"
    assert ev('date("2024-12-01") + "1M"').iso() == "2025-01-01"


def test_number_of_date_is_epoch_ms():
    one_day = ev('number(date("2026-06-30")) - number(date("2026-06-29"))')
    assert one_day == 86400000


def test_string_indexing_and_length():
    assert ev('"hello".length') == 5
    assert ev("[1,2,3].length") == 3


def test_nan_inf_serialize_to_null():
    assert evj("1 / 0") is None  # Infinity -> null in JSON
    assert math.isinf(ev("1 / 0"))
