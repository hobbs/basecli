"""The view-type registry is load-bearing: unknown types error until registered."""

import textwrap

import pytest
import yaml

from conftest import FIXTURE_VAULT, TODAY, NOW
from basecli import engine
from basecli.base import Base
from basecli.engine import run_view, register_view_type
from basecli.errors import SchemaError
from basecli.vault import Vault


def _base(view_type):
    data = yaml.safe_load(textwrap.dedent(f"""
        filters:
          - 'file.inFolder("tasks")'
        views:
          - type: {view_type}
            name: V
            order: [file.name]
            limit: 1
    """))
    return Base(data, source_path="x.base")


@pytest.fixture(scope="module")
def vault():
    return Vault(FIXTURE_VAULT).scan()


@pytest.mark.parametrize("vtype", ["table", "list", "cards", "map"])
def test_builtin_view_types_accepted(vault, vtype):
    base = _base(vtype)
    result = run_view(base, vault, base.views[0], today=TODAY, now=NOW)
    assert result["view"]["type"] == vtype
    assert result["row_count"] == 1


def test_unknown_view_type_errors(vault):
    base = _base("kanban")
    with pytest.raises(SchemaError) as exc:
        run_view(base, vault, base.views[0], today=TODAY, now=NOW)
    assert "kanban" in str(exc.value)


def test_register_view_type_makes_it_accepted(vault):
    assert "timeline" not in engine.VIEW_TYPES
    try:
        register_view_type("timeline")
        base = _base("timeline")
        result = run_view(base, vault, base.views[0], today=TODAY, now=NOW)
        assert result["view"]["type"] == "timeline"
        assert result["row_count"] == 1  # renders as tabular data
    finally:
        engine.VIEW_TYPES.discard("timeline")
