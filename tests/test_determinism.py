"""Determinism: identical inputs + --today produce byte-identical JSON."""

import io
from contextlib import redirect_stdout

from conftest import FIXTURE_BASE, FIXTURE_VAULT
from basecli.cli import run


def _render_json():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = run([FIXTURE_BASE, "--vault", FIXTURE_VAULT,
                  "--today", "2026-06-30", "--format", "json"])
    assert rc == 0
    return buf.getvalue()


def test_byte_identical_across_runs():
    a = _render_json()
    b = _render_json()
    assert a == b


def test_all_views_deterministic():
    from basecli.base import load_base
    base = load_base(FIXTURE_BASE)
    for name in base.view_names():
        buf1, buf2 = io.StringIO(), io.StringIO()
        with redirect_stdout(buf1):
            run([FIXTURE_BASE, "--vault", FIXTURE_VAULT, "--today", "2026-06-30",
                 "--view", name, "--format", "json"])
        with redirect_stdout(buf2):
            run([FIXTURE_BASE, "--vault", FIXTURE_VAULT, "--today", "2026-06-30",
                 "--view", name, "--format", "json"])
        assert buf1.getvalue() == buf2.getvalue(), name
