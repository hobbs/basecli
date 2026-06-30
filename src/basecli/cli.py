"""argparse front door for basecli."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import Any, List, Optional

from . import __version__
from .base import load_base
from .engine import list_views, run_view
from .errors import BaseCliError, UsageError
from .values import BDate
from .vault import Vault, find_vault_root


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="basecli",
        description="Headless renderer for Obsidian Bases (.base) files.",
    )
    p.add_argument("base_file", help="Path to a .base file (or a markdown file with a ```base block; see --embedded).")
    p.add_argument("--vault", metavar="PATH", default=None,
                   help="Vault root to scan. Default: nearest ancestor with a .obsidian/ folder, else cwd.")
    p.add_argument("--view", metavar="NAME", default=None,
                   help="View to render. Default: first view in the file.")
    p.add_argument("--list-views", action="store_true",
                   help="Print available view names (+ layout, row counts) and exit.")
    p.add_argument("--format", dest="fmt", choices=["json", "table", "markdown", "csv"],
                   default="json", help="Output format (default: json).")
    p.add_argument("--today", metavar="YYYY-MM-DD", default=None,
                   help='Inject "today"/"now" for deterministic output.')
    p.add_argument("--this", dest="this_path", metavar="PATH", default=None,
                   help="Resolve this.* against this file (the embedding/active file).")
    p.add_argument("--limit", type=int, default=None, help="Override the view's limit.")
    p.add_argument("--no-group", action="store_true", help="Flatten groups into a single ordered list.")
    p.add_argument("--columns", default=None, help="Override the view's column selection (comma-separated).")
    p.add_argument("--embedded", action="store_true", help="Read a ```base code block from a markdown file.")
    p.add_argument("--version", action="version", version=f"basecli {__version__}")
    return p


def _resolve_today(today_arg: Optional[str]):
    if today_arg:
        d = BDate.parse(today_arg)
        if d is None:
            raise UsageError(f"Invalid --today value: {today_arg!r} (expected YYYY-MM-DD)")
        today = d.date_only()
        now = BDate(today.dt, has_time=True)
        return today, now
    now_dt = _dt.datetime.now()
    today = BDate(_dt.datetime(now_dt.year, now_dt.month, now_dt.day))
    now = BDate(now_dt, has_time=True)
    return today, now


def _build_this(vault: Vault, this_path: str) -> Any:
    abspath = os.path.abspath(this_path)
    bf = None
    for f in vault.files:
        if os.path.abspath(f.abspath) == abspath:
            bf = f
            break
    if bf is None:
        # Resolve relative to vault root by path.
        rel = os.path.relpath(abspath, vault.root).replace(os.sep, "/")
        bf = vault.by_path.get(rel)
    if bf is None:
        raise UsageError(f"--this file is not in the vault: {this_path}")
    obj = dict(bf.properties)
    obj["file"] = bf
    return obj


def run(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not os.path.isfile(args.base_file):
        raise UsageError(f"Base file not found: {args.base_file}")

    base = load_base(args.base_file, embedded=args.embedded)

    vault_root = args.vault or find_vault_root(args.base_file)
    vault = Vault(vault_root).scan()

    today, now = _resolve_today(args.today)
    this_obj = _build_this(vault, args.this_path) if args.this_path else None

    if args.list_views:
        views = list_views(base, vault, today=today, now=now, this_obj=this_obj)
        if args.fmt == "json":
            sys.stdout.write(json.dumps({"base": os.path.basename(args.base_file),
                                         "views": views}, indent=2, ensure_ascii=False) + "\n")
        else:
            for v in views:
                sys.stdout.write(f"{v['name']}\t[{v['type']}]\t{v['row_count']} rows\n")
        return 0

    view = base.find_view(args.view)
    columns_override = None
    if args.columns is not None:
        columns_override = [c.strip() for c in args.columns.split(",") if c.strip()]

    result = run_view(
        base, vault, view,
        today=today, now=now, this_obj=this_obj,
        limit_override=args.limit,
        columns_override=columns_override,
        no_group=args.no_group,
    )

    from .formatters import format_result
    output = format_result(result, args.fmt)
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(argv)
    except BaseCliError as err:
        sys.stderr.write(json.dumps({"error": err.to_dict()}, ensure_ascii=False) + "\n")
        return 1
    except BrokenPipeError:  # pragma: no cover
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
