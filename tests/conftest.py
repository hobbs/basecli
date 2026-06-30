"""Shared test fixtures and helpers."""

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from basecli.evaluator import Context, Env, eval_string  # noqa: E402
from basecli.values import BDate, json_value  # noqa: E402
import basecli.functions  # noqa: E402,F401  (registers functions)

FIXTURE_VAULT = os.path.join(os.path.dirname(__file__), "fixtures", "vault")
FIXTURE_BASE = os.path.join(FIXTURE_VAULT, "tasks.base")

TODAY = BDate(dt.datetime(2026, 6, 30))
NOW = BDate(dt.datetime(2026, 6, 30), has_time=True)


def make_env(vault=None):
    return Env(vault=vault, today=TODAY, now=NOW)


def ev(expr, note=None):
    """Evaluate an expression string and return the raw value."""
    ctx = Context(make_env(), note=note or {})
    return eval_string(expr, ctx)


def evj(expr, note=None):
    """Evaluate and return the JSON-serializable value (for comparisons)."""
    return json_value(ev(expr, note))


@pytest.fixture
def today():
    return TODAY
