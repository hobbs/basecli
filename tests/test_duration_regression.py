"""Regression for the documented Duration behavior.

`date - date` returns a Duration, which has *no* numeric methods. Calling
`.round()` on it must raise the same error Obsidian does. To get a numeric day
count the formula must coerce via `number()`, since `number(date)` is epoch ms.
"""

import pytest

from conftest import ev
from basecli.errors import EvalError
from basecli.values import BDuration


def test_date_minus_date_is_duration():
    result = ev('date("2026-06-30") - date("2026-04-27")')
    assert isinstance(result, BDuration)


def test_round_on_duration_errors_like_obsidian():
    with pytest.raises(EvalError) as exc:
        ev('(date("2026-06-30") - date("2026-04-27")).round()')
    assert str(exc.value) == 'Cannot find function "round" on type Duration'


def test_other_numeric_methods_also_error_on_duration():
    for m in ("abs", "floor", "ceil", "toFixed"):
        with pytest.raises(EvalError):
            ev(f'(date("2026-06-30") - date("2026-04-27")).{m}()')


def test_number_coercion_gives_integer_day_delta():
    # The documented workaround: coerce both endpoints to epoch ms first.
    days = ev('((number(date("2026-06-29")) - number(date("2026-06-30"))) / 86400000).round()')
    assert days == -1

    days2 = ev('((number(date("2026-04-27")) - number(date("2026-06-30"))) / 86400000).round()')
    assert days2 == -64


def test_date_isEmpty_always_false():
    # Documented quirk: a Date is never "empty"; emptiness is via truthiness.
    assert ev('date("2026-06-30").isEmpty()') is False
