"""File-property and `this`-resolution tests against the synthetic fixture vault."""

import datetime as dt
import os

import pytest

from conftest import FIXTURE_VAULT
from basecli.evaluator import Context, Env, eval_string
from basecli.values import BDate
from basecli.vault import Vault, find_vault_root


@pytest.fixture(scope="module")
def vault():
    return Vault(FIXTURE_VAULT).scan()


def _ctx(vault, bf):
    env = Env(vault=vault, today=BDate(dt.datetime(2026, 6, 30)),
              now=BDate(dt.datetime(2026, 6, 30)))
    return Context(env, file=bf)


def _file(vault, basename):
    return next(f for f in vault.files if f.basename == basename)


def test_find_vault_root_uses_obsidian_marker():
    base_file = os.path.join(FIXTURE_VAULT, "tasks.base")
    assert os.path.abspath(find_vault_root(base_file)) == os.path.abspath(FIXTURE_VAULT)


def test_file_fields(vault):
    bf = _file(vault, "migrate-legacy-database")
    ctx = _ctx(vault, bf)
    assert eval_string("file.name", ctx) == "migrate-legacy-database.md"
    assert eval_string("file.basename", ctx) == "migrate-legacy-database"
    assert eval_string("file.ext", ctx) == "md"
    assert eval_string("file.folder", ctx) == "tasks"
    assert eval_string("file.path", ctx) == "tasks/migrate-legacy-database.md"


def test_has_tag_nested_and_in_folder(vault):
    bf = _file(vault, "migrate-legacy-database")  # tags: work/eng
    ctx = _ctx(vault, bf)
    assert eval_string('file.hasTag("work")', ctx) is True       # nested match
    assert eval_string('file.hasTag("work/eng")', ctx) is True
    assert eval_string('file.hasTag("personal")', ctx) is False
    assert eval_string('file.inFolder("tasks")', ctx) is True    # folder
    assert eval_string('file.inFolder("notes")', ctx) is False


def test_in_folder_matches_subfolders(vault):
    archived = _file(vault, "refactor-auth-module")  # tasks/archive/
    ctx = _ctx(vault, archived)
    assert eval_string("file.folder", ctx) == "tasks/archive"
    assert eval_string('file.inFolder("tasks")', ctx) is True    # subfolder match
    assert eval_string('file.folder.contains("archive")', ctx) is True


def test_as_link_and_has_property(vault):
    bf = _file(vault, "migrate-legacy-database")
    ctx = _ctx(vault, bf)
    assert eval_string('file.hasProperty("status")', ctx) is True
    assert eval_string('file.hasProperty("nonexistent")', ctx) is False
    link = eval_string("file.asLink()", ctx)
    assert link.target == "tasks/migrate-legacy-database.md"


def test_this_resolution(vault):
    bf = _file(vault, "deploy-release-v2")
    this_obj = dict(bf.properties)
    this_obj["file"] = bf
    env = Env(vault=vault, today=BDate(dt.datetime(2026, 6, 30)),
              now=BDate(dt.datetime(2026, 6, 30)), this_obj=this_obj)
    ctx = Context(env, file=bf)
    assert eval_string("this.file.name", ctx) == "deploy-release-v2.md"
    assert eval_string("this.status", ctx) == "open"
