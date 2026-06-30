"""Integration test against the synthetic fixture vault (tasks.base).

The fixture is entirely fictional (see tests/fixtures/vault). The expected
numbers below are the known-good result for `--today 2026-06-30`.
"""

import pytest

from conftest import FIXTURE_BASE, FIXTURE_VAULT, TODAY, NOW
from basecli.base import load_base
from basecli.engine import run_view, list_views
from basecli.vault import Vault


@pytest.fixture(scope="module")
def loaded():
    base = load_base(FIXTURE_BASE)
    vault = Vault(FIXTURE_VAULT).scan()
    return base, vault


def _render(loaded, view_name=None, **kw):
    base, vault = loaded
    view = base.find_view(view_name)
    return run_view(base, vault, view, today=TODAY, now=NOW, **kw)


def _group_counts(result):
    return {g["key"]: len(g["rows"]) for g in result["groups"]}


def test_urgency_view_groups(loaded):
    result = _render(loaded, "🎯 By urgency")
    counts = _group_counts(result)
    assert counts["1 · 🔴 Overdue"] == 3
    assert counts["2 · 🟠 Today"] == 2
    assert counts["3 · 🟡 This week"] == 2
    assert counts["4 · 🟢 Later"] == 1
    assert counts["5 · 📋 Someday / no date"] == 4
    assert result["row_count"] == 12


def test_urgency_named_overdue_values(loaded):
    result = _render(loaded, "🎯 By urgency")
    overdue = next(g for g in result["groups"] if g["key"] == "1 · 🔴 Overdue")
    by_name = {r["file"]["basename"]: r["cells"]["formula.days_left"]["value"]
               for r in overdue["rows"]}
    assert by_name["migrate-legacy-database"] == -60
    assert by_name["renew-ssl-certificate"] == -7
    assert by_name["submit-expense-report"] == -1


def test_urgency_this_week_and_later_values(loaded):
    result = _render(loaded, "🎯 By urgency")
    week = next(g for g in result["groups"] if g["key"] == "3 · 🟡 This week")
    week_vals = {r["file"]["basename"]: r["cells"]["formula.days_left"]["value"]
                 for r in week["rows"]}
    assert week_vals["review-pull-requests"] == 2
    assert week_vals["water-the-plants"] == 5

    later = next(g for g in result["groups"] if g["key"] == "4 · 🟢 Later")
    assert later["rows"][0]["cells"]["formula.days_left"]["value"] == 30


def test_category_split_in_urgency(loaded):
    result = _render(loaded, "🎯 By urgency")
    cats = {}
    for g in result["groups"]:
        for r in g["rows"]:
            c = r["cells"]["formula.category"]["value"]
            cats[c] = cats.get(c, 0) + 1
    assert cats["💼 Work"] == 7
    assert cats["🏠 Personal"] == 5


def test_view_row_counts(loaded):
    base, vault = loaded
    counts = {v["name"]: v["row_count"] for v in list_views(base, vault, today=TODAY, now=NOW)}
    assert counts["💼 Work"] == 7
    assert counts["🏠 Personal"] == 5
    assert counts["📋 Backlog (no due date)"] == 4
    assert counts["✅ Done"] == 1


def test_builtin_min_summary(loaded):
    result = _render(loaded, "🎯 By urgency")
    summ = {g["key"]: g["summaries"].get("formula.days_left") for g in result["groups"]}
    assert summ["1 · 🔴 Overdue"]["name"] == "Min"
    assert summ["1 · 🔴 Overdue"]["value"] == -60
    assert summ["2 · 🟠 Today"]["value"] == 0
    assert summ["4 · 🟢 Later"]["value"] == 30
    # No numeric values in the Someday group -> empty.
    assert summ["5 · 📋 Someday / no date"]["value"] is None


def test_custom_summary_formula(loaded):
    # `customAvg: values.average().round(1)` on the Work view's Overdue group:
    # mean(-60, -7, -1) = -22.666… rounded to -22.7.
    result = _render(loaded, "💼 Work")
    overdue = next(g for g in result["groups"] if g["key"] == "1 · 🔴 Overdue")
    cell = overdue["summaries"]["formula.days_left"]
    assert cell["name"] == "customAvg"
    assert cell["value"] == -22.7


def test_archive_is_excluded(loaded):
    # `!file.folder.contains("archive")` drops tasks/archive/* — including one
    # that is due today and would otherwise land in the Today bucket.
    result = _render(loaded, "🎯 By urgency")
    names = {r["file"]["basename"] for g in result["groups"] for r in g["rows"]}
    for r in (r for g in result["groups"] for r in g["rows"]):
        assert "archive" not in r["file"]["path"]
    assert "refactor-auth-module" not in names  # archived, due today


def test_type_filter_excludes_non_tasks(loaded):
    # `type == "task"` drops the note that lives in tasks/ but is type: note.
    result = _render(loaded, "🎯 By urgency")
    names = {r["file"]["basename"] for g in result["groups"] for r in g["rows"]}
    assert "project-overview" not in names
    assert "meeting-notes" not in names


def test_done_view_counts_only_done(loaded):
    result = _render(loaded, "✅ Done")
    assert result["row_count"] == 1
    assert result["groups"][0]["rows"][0]["file"]["basename"] == "close-stale-issues"


def test_columns_override(loaded):
    result = _render(loaded, "🎯 By urgency", columns_override=["file.name"])
    assert [c["id"] for c in result["columns"]] == ["file.name"]
    row = result["groups"][0]["rows"][0]
    assert list(row["cells"].keys()) == ["file.name"]


def test_no_group_flattens(loaded):
    result = _render(loaded, "🎯 By urgency", no_group=True)
    assert len(result["groups"]) == 1
    assert result["groups"][0]["key"] is None
    assert len(result["groups"][0]["rows"]) == 12


def test_limit_override(loaded):
    result = _render(loaded, "🎯 By urgency", limit_override=3)
    assert result["row_count"] == 3


def test_hastag_matches_nested(loaded):
    # work/eng must match hasTag("work"); personal tasks must not appear.
    result = _render(loaded, "💼 Work")
    names = {r["file"]["basename"] for g in result["groups"] for r in g["rows"]}
    assert "migrate-legacy-database" in names  # tags: work/eng
    assert "call-dentist" not in names         # tags: personal/health
