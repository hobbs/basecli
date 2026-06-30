"""Integration tests over a synthetic, non-task `.base` (a fictional book library).

This fixture exists to prove the engine is a generic `.base` implementation, not
a tasks tool: it exercises non-task frontmatter, date-field / list / object /
string formulas, links + backlinks (reverse-index), a cards layout, and the full
spread of built-in summary aggregations. Every note is invented — no personal
data.
"""

import datetime as dt
import os

import pytest

from basecli.base import load_base
from basecli.engine import run_view, list_views
from basecli.values import BDate
from basecli.vault import Vault

LIBRARY_VAULT = os.path.join(os.path.dirname(__file__), "fixtures", "library")
LIBRARY_BASE = os.path.join(LIBRARY_VAULT, "library.base")
TODAY = BDate(dt.datetime(2026, 6, 30))
NOW = BDate(dt.datetime(2026, 6, 30), has_time=True)


@pytest.fixture(scope="module")
def loaded():
    return load_base(LIBRARY_BASE), Vault(LIBRARY_VAULT).scan()


def _render(loaded, view_name, **kw):
    base, vault = loaded
    return run_view(base, vault, base.find_view(view_name), today=TODAY, now=NOW, **kw)


def _cells_by_name(result):
    return {r["file"]["basename"]: r["cells"]
            for g in result["groups"] for r in g["rows"]}


def test_view_inventory(loaded):
    base, vault = loaded
    counts = {v["name"]: (v["type"], v["row_count"])
              for v in list_views(base, vault, today=TODAY, now=NOW)}
    assert counts["🃏 Covers"] == ("cards", 8)
    assert counts["📚 All books"] == ("table", 8)
    assert counts["🚀 Unread sci-fi"] == ("table", 2)
    assert counts["🔗 Backlinks"] == ("table", 1)


def test_non_book_note_excluded(loaded):
    # `type == "book"` must drop notes/reading-log.md.
    result = _render(loaded, "📚 All books")
    names = {r["file"]["basename"] for g in result["groups"] for r in g["rows"]}
    assert "reading-log" not in names
    assert result["row_count"] == 8


def test_summaries_all_books(loaded):
    s = _render(loaded, "📚 All books")["groups"][0]["summaries"]
    assert s["rating"] == {"name": "Average", "value": 4, "display": "4"}
    assert s["pages"]["name"] == "Sum" and s["pages"]["value"] == 2602
    assert s["author"] == {"name": "Unique", "value": 4, "display": "4"}      # 4 distinct authors
    assert s["read"] == {"name": "Checked", "value": 5, "display": "5"}        # 5 read
    assert s["published"]["name"] == "Latest" and s["published"]["value"] == "2024-01-30"


def test_summaries_stats_view(loaded):
    s = _render(loaded, "🔢 Stats")["groups"][0]["summaries"]
    assert s["rating"]["name"] == "Max" and s["rating"]["value"] == 5
    assert s["pages"]["name"] == "Min" and s["pages"]["value"] == 190
    assert s["published"]["name"] == "Earliest" and s["published"]["value"] == "2012-09-09"
    assert s["read"]["name"] == "Unchecked" and s["read"]["value"] == 3
    assert s["genre"]["name"] == "Filled" and s["genre"]["value"] == 8


def test_summaries_more_stats_view(loaded):
    s = _render(loaded, "📊 More stats")["groups"][0]["summaries"]
    assert s["rating"]["name"] == "Median" and s["rating"]["value"] == 4
    assert s["pages"]["name"] == "Range" and s["pages"]["value"] == 322       # 512 - 190
    assert s["formula.decade"]["name"] == "Stddev" and s["formula.decade"]["value"] == 5
    assert s["sequel_to"]["name"] == "Empty" and s["sequel_to"]["value"] == 7  # only 1 has it


def test_string_and_list_formulas(loaded):
    # author_initials uses split + map(value.slice) + join; top_genre indexes a list.
    cols = ["formula.author_initials", "formula.rating_stars", "formula.length_label",
            "formula.top_genre"]
    cells = _cells_by_name(_render(loaded, "📚 All books", columns_override=cols))
    assert cells["the-glass-forest"]["formula.author_initials"]["value"] == "MQ"
    assert cells["echoes-of-tomorrow"]["formula.author_initials"]["value"] == "DA"
    assert cells["the-glass-forest"]["formula.rating_stars"]["value"] == "★★★★★"
    assert cells["quantum-gardens"]["formula.length_label"]["value"] == "long"      # 512 pages
    assert cells["the-glass-forest"]["formula.length_label"]["value"] == "medium"   # 320 pages
    assert cells["cooking-with-fire"]["formula.length_label"]["value"] == "short"   # 190 pages
    assert cells["echoes-of-tomorrow"]["formula.top_genre"]["value"] == "sci-fi"


def test_date_field_and_comparison_formulas(loaded):
    cols = ["formula.decade", "formula.is_recent"]
    cells = _cells_by_name(_render(loaded, "📚 All books", columns_override=cols))
    assert cells["the-glass-forest"]["formula.decade"]["value"] == 2010   # 2019 -> 2010
    assert cells["midnight-equations"]["formula.decade"]["value"] == 2020  # 2024 -> 2020
    assert cells["paper-cities"]["formula.is_recent"]["value"] is True      # 2020-08-18 >= 2020-01-01
    assert cells["the-silent-tide"]["formula.is_recent"]["value"] is False  # 2015-11-20


def test_links_backlinks_and_haslink(loaded):
    cols = ["formula.backlink_count", "formula.links_to_echoes"]
    cells = _cells_by_name(_render(loaded, "📚 All books", columns_override=cols))
    # quantum-gardens links to echoes (frontmatter wikilink) -> echoes has 1 backlink.
    assert cells["echoes-of-tomorrow"]["formula.backlink_count"]["value"] == 1
    assert cells["quantum-gardens"]["formula.backlink_count"]["value"] == 0
    assert cells["quantum-gardens"]["formula.links_to_echoes"]["value"] is True
    assert cells["the-glass-forest"]["formula.links_to_echoes"]["value"] is False


def test_backlinks_view(loaded):
    result = _render(loaded, "🔗 Backlinks")
    names = [r["file"]["basename"] for g in result["groups"] for r in g["rows"]]
    assert names == ["echoes-of-tomorrow"]


def test_filter_uses_list_contains_and_boolean(loaded):
    # read == false AND genre.contains("sci-fi")
    result = _render(loaded, "🚀 Unread sci-fi")
    names = [r["file"]["basename"] for g in result["groups"] for r in g["rows"]]
    assert set(names) == {"quantum-gardens", "midnight-equations"}


def test_cards_layout_runs_as_rows(loaded):
    # Cards is accepted; the engine returns the same rows+columns structure.
    result = _render(loaded, "🃏 Covers")
    assert result["view"]["type"] == "cards"
    assert result["row_count"] == 8
    # Grouped by length_label -> short / medium / long groups present.
    keys = {g["key"] for g in result["groups"]}
    assert {"short", "medium", "long"} <= keys
