"""Render an engine result dict as json / table / markdown / csv.

All four are renderings of the *same* data; ``json`` is the canonical,
machine-parseable contract (see README). ``table``/``markdown``/``csv`` are
human-facing.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List


def format_result(result: Dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return _json(result)
    if fmt == "table":
        return _table(result)
    if fmt == "markdown":
        return _markdown(result)
    if fmt == "csv":
        return _csv(result)
    raise ValueError(f"Unknown format: {fmt}")


def _json(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)


def _columns(result):
    return [c["id"] for c in result["columns"]], [c["displayName"] for c in result["columns"]]


def _grouped(result) -> bool:
    groups = result["groups"]
    return not (len(groups) == 1 and groups[0]["key"] is None)


def _table(result: Dict[str, Any]) -> str:
    ids, headers = _columns(result)
    lines: List[str] = []
    view = result["view"]
    lines.append(f"{view['name']}  [{view['type']}]  ({result['row_count']} rows)")
    lines.append("")
    grouped = _grouped(result)
    for group in result["groups"]:
        rows = group["rows"]
        if grouped:
            lines.append(f"▸ {group['key']}  ({len(rows)})")
        table_rows = [[_cell(r, cid) for cid in ids] for r in rows]
        widths = [len(h) for h in headers]
        for tr in table_rows:
            for i, cell in enumerate(tr):
                widths[i] = max(widths[i], len(cell))
        lines.append("  " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
        lines.append("  " + "-+-".join("-" * widths[i] for i in range(len(headers))))
        for tr in table_rows:
            lines.append("  " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(tr)))
        for prop, summ in group.get("summaries", {}).items():
            lines.append(f"  ∑ {prop}: {summ['name']} = {summ['display']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown(result: Dict[str, Any]) -> str:
    ids, headers = _columns(result)
    lines: List[str] = []
    view = result["view"]
    lines.append(f"# {view['name']}")
    lines.append("")
    lines.append(f"_{view['type']} · {result['row_count']} rows_")
    lines.append("")
    grouped = _grouped(result)
    for group in result["groups"]:
        rows = group["rows"]
        if grouped:
            lines.append(f"## {group['key']} ({len(rows)})")
            lines.append("")
        lines.append("| " + " | ".join(_md_escape(h) for h in headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for r in rows:
            lines.append("| " + " | ".join(_md_escape(_cell(r, cid)) for cid in ids) + " |")
        for prop, summ in group.get("summaries", {}).items():
            lines.append("")
            lines.append(f"**{prop}** — {summ['name']}: {summ['display']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _csv(result: Dict[str, Any]) -> str:
    ids, headers = _columns(result)
    buf = io.StringIO()
    writer = csv.writer(buf)
    grouped = _grouped(result)
    header_row = (["group"] if grouped else []) + headers + ["file.path"]
    writer.writerow(header_row)
    for group in result["groups"]:
        for r in group["rows"]:
            prefix = [group["key"] if group["key"] is not None else ""] if grouped else []
            writer.writerow(prefix + [_cell(r, cid) for cid in ids] + [r["file"]["path"]])
    return buf.getvalue()


def _cell(row: Dict[str, Any], col_id: str) -> str:
    cell = row["cells"].get(col_id)
    if cell is None:
        return ""
    return str(cell.get("display", ""))


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
