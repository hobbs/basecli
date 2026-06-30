"""Split YAML frontmatter from a note body and extract inline ``#tags``."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import yaml

_FM_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)

# Inline tags: #tag, #tag/nested, #tag-with-dashes. Must be preceded by start
# or whitespace (so we don't match URL fragments or "C#" mid-word). Excludes
# pure-numeric tags (#123) which Obsidian treats as not-a-tag.
_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z0-9_][\w/\-]*)")

# Wikilinks [[target]] / [[target|alias]] and embeds ![[...]].
_LINK_RE = re.compile(r"(!?)\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")

# Markdown links [text](target) where target is not a URL scheme.
_MDLINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")

_CODE_FENCE_RE = re.compile(r"^(```|~~~)")


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Return ``(frontmatter_dict, body)``.

    A malformed or non-mapping frontmatter block yields an empty dict and the
    original text as the body (we never raise here — a single bad note should
    not abort a vault scan).
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end():]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}, body
    if not isinstance(data, dict):
        return {}, body
    return data, body


def _strip_code_blocks(body: str) -> str:
    """Remove fenced code blocks and inline code so #tags inside them don't count."""
    out_lines: List[str] = []
    in_fence = False
    for line in body.splitlines():
        if _CODE_FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            out_lines.append(line)
    text = "\n".join(out_lines)
    # Drop inline `code` spans.
    text = re.sub(r"`[^`]*`", " ", text)
    return text


def extract_inline_tags(body: str) -> List[str]:
    cleaned = _strip_code_blocks(body)
    seen: List[str] = []
    for m in _TAG_RE.finditer(cleaned):
        tag = m.group(1)
        if tag.isdigit():
            continue
        if tag not in seen:
            seen.append(tag)
    return seen


def extract_links(body: str) -> List[str]:
    """Internal link targets from wikilinks and relative markdown links."""
    targets: List[str] = []
    for m in _LINK_RE.finditer(body):
        targets.append(m.group(2).strip())
    for m in _MDLINK_RE.finditer(body):
        tgt = m.group(1).strip()
        if "://" in tgt or tgt.startswith("#") or tgt.startswith("mailto:"):
            continue
        targets.append(tgt)
    return targets


def extract_embeds(body: str) -> List[str]:
    embeds: List[str] = []
    for m in _LINK_RE.finditer(body):
        if m.group(1) == "!":
            embeds.append(m.group(2).strip())
    return embeds


def normalize_frontmatter_tags(fm: Dict[str, Any]) -> List[str]:
    """Frontmatter ``tags`` may be a list, a comma/space string, or absent."""
    raw = fm.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,\s]+", raw.strip())
        return [p.lstrip("#") for p in parts if p]
    if isinstance(raw, list):
        return [str(t).lstrip("#") for t in raw if t is not None]
    return [str(raw).lstrip("#")]
