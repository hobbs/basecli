"""Vault scanning: build the file index, compute file properties, backlinks."""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, List, Optional

from . import frontmatter as fm
from .errors import VaultError
from .values import BDate, BLink


def find_vault_root(start: str) -> str:
    """Nearest ancestor directory containing a ``.obsidian/`` folder, else cwd.

    ``start`` may be a file or directory.
    """
    path = os.path.abspath(start)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    cur = path
    while True:
        if os.path.isdir(os.path.join(cur, ".obsidian")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return path


def _normalize_fm_value(value: Any) -> Any:
    """Convert YAML-parsed dates to BDate; recurse into lists/dicts."""
    if isinstance(value, _dt.datetime):
        return BDate.from_value(value)
    if isinstance(value, _dt.date):
        return BDate.from_value(value)
    if isinstance(value, list):
        return [_normalize_fm_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_fm_value(v) for k, v in value.items()}
    return value


class BFile:
    """A Bases File object.

    Fields are computed eagerly at scan time except ``backlinks``, which the
    vault fills in after the reverse index is built.
    """

    _is_bfile = True

    __slots__ = (
        "path", "abspath", "name", "basename", "folder", "ext",
        "size", "ctime", "mtime", "properties", "_tags_fm", "_tags_inline",
        "links", "embeds", "_backlinks", "_vault",
    )

    def __init__(self, abspath: str, rel_path: str, vault: "Vault"):
        self.abspath = abspath
        self.path = rel_path.replace(os.sep, "/")
        self.name = os.path.basename(self.path)
        base, ext = os.path.splitext(self.name)
        self.basename = base
        self.ext = ext[1:] if ext.startswith(".") else ext
        folder = os.path.dirname(self.path)
        self.folder = folder
        self._vault = vault
        self._backlinks: List[BFile] = []
        # Filled by _load.
        self.size = 0
        self.ctime: Optional[BDate] = None
        self.mtime: Optional[BDate] = None
        self.properties: Dict[str, Any] = {}
        self._tags_fm: List[str] = []
        self._tags_inline: List[str] = []
        self.links: List[BLink] = []
        self.embeds: List[str] = []

    # -- fields exposed to the engine ---------------------------------------
    @property
    def file(self) -> "BFile":
        return self

    @property
    def tags(self) -> List[str]:
        out: List[str] = []
        for t in self._tags_fm + self._tags_inline:
            if t not in out:
                out.append(t)
        return out

    @property
    def backlinks(self) -> List["BFile"]:
        return list(self._backlinks)

    # -- methods ------------------------------------------------------------
    def hasTag(self, *names: str) -> bool:
        own = self.tags
        for query in names:
            q = str(query).lstrip("#")
            for t in own:
                if t == q or t.startswith(q + "/"):
                    return True
        return False

    def inFolder(self, folder: str) -> bool:
        folder = str(folder).strip("/")
        f = self.folder.strip("/")
        if folder == "":
            return True
        return f == folder or f.startswith(folder + "/")

    def hasProperty(self, name: str) -> bool:
        return name in self.properties

    def hasLink(self, other: Any) -> bool:
        target_paths = set()
        target_names = set()
        if isinstance(other, BFile):
            target_paths.add(other.path)
            target_names.add(other.basename)
            target_names.add(other.name)
        elif isinstance(other, BLink):
            target_names.add(other.target)
        else:
            s = str(other)
            target_names.add(s)
            target_paths.add(s)
        for link in self.links:
            resolved = self._vault.resolve_link(link.target)
            if resolved is not None and resolved.path in target_paths:
                return True
            raw = link.target
            base = os.path.splitext(os.path.basename(raw))[0]
            if raw in target_names or base in target_names:
                return True
        return False

    def asLink(self, display: Any = None) -> BLink:
        return BLink(self.path, display_text=display)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BFile) and other.path == self.path

    def __hash__(self) -> int:
        return hash(self.path)

    def __repr__(self) -> str:
        return f"BFile({self.path!r})"


class Vault:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.files: List[BFile] = []
        self.by_path: Dict[str, BFile] = {}
        self._by_basename: Dict[str, List[BFile]] = {}
        self._scanned = False

    # -- scanning -----------------------------------------------------------
    def scan(self) -> "Vault":
        if self._scanned:
            return self
        if not os.path.isdir(self.root):
            raise VaultError(f"Vault root is not a directory: {self.root}")
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Skip hidden/system dirs (.obsidian, .git, .trash, ...).
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                abspath = os.path.join(dirpath, fn)
                rel = os.path.relpath(abspath, self.root)
                bf = BFile(abspath, rel, self)
                self._load(bf)
                self.files.append(bf)
                self.by_path[bf.path] = bf
                self._by_basename.setdefault(bf.basename, []).append(bf)
        self._build_backlinks()
        self._scanned = True
        return self

    def _load(self, bf: BFile) -> None:
        try:
            with open(bf.abspath, "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            text = ""
        data, body = fm.split_frontmatter(text)
        bf.properties = {k: _normalize_fm_value(v) for k, v in data.items()}
        bf._tags_fm = fm.normalize_frontmatter_tags(data)
        bf._tags_inline = fm.extract_inline_tags(body)
        link_targets = fm.extract_links(body) + _frontmatter_links(data)
        bf.links = [BLink(t) for t in link_targets]
        bf.embeds = fm.extract_embeds(body)
        try:
            st = os.stat(bf.abspath)
            bf.size = st.st_size
            bf.ctime = BDate(_dt.datetime.utcfromtimestamp(getattr(st, "st_birthtime", st.st_ctime)), has_time=True)
            bf.mtime = BDate(_dt.datetime.utcfromtimestamp(st.st_mtime), has_time=True)
        except OSError:
            pass

    def _build_backlinks(self) -> None:
        for bf in self.files:
            seen = set()
            for link in bf.links:
                target = self.resolve_link(link.target)
                if target is not None and target.path not in seen and target.path != bf.path:
                    seen.add(target.path)
                    target._backlinks.append(bf)

    # -- link resolution ----------------------------------------------------
    def resolve_link(self, target: str) -> Optional[BFile]:
        t = target.strip()
        if t.startswith("[[") and t.endswith("]]"):
            t = t[2:-2]
        if "|" in t:
            t = t.split("|", 1)[0]
        if "#" in t:
            t = t.split("#", 1)[0]
        t = t.strip().replace(os.sep, "/")
        if not t:
            return None
        # Exact path, then with .md appended.
        if t in self.by_path:
            return self.by_path[t]
        if (t + ".md") in self.by_path:
            return self.by_path[t + ".md"]
        # Basename match.
        base = os.path.splitext(os.path.basename(t))[0]
        candidates = self._by_basename.get(base)
        if candidates:
            return candidates[0]
        return None


def _frontmatter_links(data: Dict[str, Any]) -> List[str]:
    """Pull ``[[wikilink]]`` targets out of frontmatter string values."""
    out: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[[") and s.endswith("]]"):
                out.append(s[2:-2])
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    for value in data.values():
        walk(value)
    return out
