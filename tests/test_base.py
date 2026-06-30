"""Base loading, formula topological ordering, circular-reference detection."""

import textwrap

import pytest

from basecli.base import Base, load_base
from basecli.errors import SchemaError


def _base(yaml_text):
    import yaml
    return Base(yaml.safe_load(textwrap.dedent(yaml_text)), source_path="x.base")


def test_formula_topo_order_resolves_dependencies():
    b = _base("""
        formulas:
          c: 'formula.b + 1'
          b: 'formula.a + 1'
          a: '1'
        views:
          - type: table
            name: V
    """)
    # `a` must come before `b` before `c`.
    assert b.formula_order.index("a") < b.formula_order.index("b") < b.formula_order.index("c")


def test_circular_formula_reference_raises():
    with pytest.raises(SchemaError) as exc:
        _base("""
            formulas:
              a: 'formula.b'
              b: 'formula.a'
            views:
              - type: table
                name: V
        """)
    assert "Circular reference" in str(exc.value)


def test_inter_formula_reference_evaluates():
    import datetime as dt
    from basecli.engine import run_view
    from basecli.values import BDate
    from basecli.vault import Vault
    import os

    # A formula chain c->b->a computed against the fixture vault.
    b = _base("""
        filters:
          - 'file.inFolder("tasks")'
        formulas:
          a: '2'
          doubled: 'formula.a * 2'
          labeled: '"=" + formula.doubled'
        views:
          - type: table
            name: V
            order: [formula.labeled]
            limit: 1
    """)
    vault_root = os.path.join(os.path.dirname(__file__), "fixtures", "vault")
    vault = Vault(vault_root).scan()
    res = run_view(b, vault, b.views[0], today=BDate(dt.datetime(2026, 6, 30)),
                   now=BDate(dt.datetime(2026, 6, 30)))
    cell = res["groups"][0]["rows"][0]["cells"]["formula.labeled"]
    assert cell["value"] == "=4"


def test_view_lookup_errors_clearly():
    b = _base("""
        views:
          - type: table
            name: Only
    """)
    with pytest.raises(SchemaError) as exc:
        b.find_view("Nope")
    assert "Nope" in str(exc.value)


def test_embedded_base_block(tmp_path):
    md = tmp_path / "note.md"
    md.write_text(textwrap.dedent("""
        # A note

        ```base
        views:
          - type: table
            name: Embedded
        ```

        trailing text
    """))
    base = load_base(str(md), embedded=True)
    assert base.view_names() == ["Embedded"]
