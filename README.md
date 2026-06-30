# basecli

A headless renderer for [Obsidian Bases](https://obsidian.md/help/bases/syntax)
`.base` files. Obsidian has **no** headless renderer for Bases — the engine only
runs inside the GUI app — so `basecli` reimplements that engine in Python so AI
agents (and humans) can read, reason about, and collaborate on the rows of a
`.base` report from the command line.

The primary consumer is an AI agent, so the default output is structured JSON and
**every row carries the underlying file path** (`file.path` + `file.abspath`) so
the agent can then open or edit the source note.

```
$ basecli tasks.base --today 2026-06-30 --format table
🎯 By urgency  [table]  (12 rows)

▸ 1 · 🔴 Overdue  (3)
  Task                       | Due        | Days left | Type   | Project
  ---------------------------+------------+-----------+--------+-------------
  migrate-legacy-database.md | 2026-05-01 | -60       | 💼 Work | work/eng
  renew-ssl-certificate.md   | 2026-06-23 | -7        | 💼 Work | work/it
  submit-expense-report.md   | 2026-06-29 | -1        | 💼 Work | work/finance
  ∑ formula.days_left: Min = -60
  ...
```

## Install

```bash
pip install -e .          # editable install; provides the `basecli` entry point
# or run without installing:
python -m basecli ...
```

Dependencies: `PyYAML`, `python-dateutil` (stdlib otherwise). Python ≥ 3.9.
Metadata is declared in `setup.cfg` so the editable install works on both modern
setuptools (PEP 621) and the older setuptools (<61) that ships in some
environments.

## Usage

```
basecli <base-file> [options]

  <base-file>           Path to a .base file. (Also accept a markdown file
                        containing a ```base code block via --embedded.)

  --vault PATH          Vault root to scan. Default: nearest ancestor dir
                        containing a .obsidian/ folder, else the base file's dir.
  --view NAME           View to render. Default: first view in the file.
  --list-views          Print available view names (+ layout, row counts) and exit.
  --format FMT          json (default) | table | markdown | csv
  --today YYYY-MM-DD    Inject "today"/"now" for deterministic output and tests.
  --this PATH           Resolve this.* against this file (the embedding/active file).
  --limit N             Override the view's limit.
  --no-group            Flatten groups into a single ordered list (key: null).
  --columns a,b,c       Override the view's `order` (column selection).
  --embedded            Read a ```base code block out of a markdown file.
  --version             Print version and exit.

Errors go to stderr as structured JSON ({"error": {...}}); exit code is non-zero.
```

### Examples

```bash
# Default JSON for the first view, deterministic "today"
basecli tasks.base --today 2026-06-30

# A specific view, as a human table
basecli tasks.base --view "🎯 By urgency" --today 2026-06-30 --format table

# List views with row counts
basecli tasks.base --list-views --today 2026-06-30

# Only the columns an agent cares about, flattened, as CSV
basecli tasks.base --today 2026-06-30 --columns file.name,formula.days_left --no-group --format csv

# A base embedded in a daily note
basecli daily/2026-06-30.md --embedded --today 2026-06-30
```

## Output contract (JSON)

JSON is the default and is stable and machine-parseable. Same inputs + `--today`
produce **byte-identical** output (`random()` is the only documented source of
non-determinism).

```jsonc
{
  "base": "tasks.base",
  "view": { "name": "🎯 By urgency", "type": "table" },
  "today": "2026-06-30",
  "columns": [
    { "id": "file.name", "displayName": "Task" },
    { "id": "due_date", "displayName": "Due" },
    { "id": "formula.days_left", "displayName": "Days left" }
  ],
  "groups": [
    {
      "key": "1 · 🔴 Overdue",
      "rows": [
        {
          "file": {
            "path": "tasks/migrate-legacy-database.md",
            "abspath": "/path/to/vault/tasks/migrate-legacy-database.md",
            "name": "migrate-legacy-database.md",
            "basename": "migrate-legacy-database"
          },
          "cells": {
            "file.name":         { "value": "migrate-legacy-database.md", "display": "migrate-legacy-database.md" },
            "due_date":          { "value": "2026-05-01", "display": "2026-05-01" },
            "formula.days_left": { "value": -60, "display": "-60" }
          }
        }
      ],
      "summaries": { "formula.days_left": { "name": "Min", "value": -60, "display": "-60" } }
    }
  ],
  "summaries": { },
  "row_count": 12
}
```

Rules:

- When ungrouped (`--no-group`, or a view without `groupBy`), a single synthetic
  group is emitted with `key: null`.
- Each cell carries both the raw `value` (typed, JSON-serializable) and a human
  `display` string.
- `file.path` and `file.abspath` are always present on every row, even if not a
  selected column.
- Per-group `summaries` map a property id → `{name, value, display}`. The
  top-level `summaries` is reserved (currently always `{}`); per-view summaries
  surface inside each group, matching the engine.
- Typed value serialization: Date → ISO string (`"2026-04-27"`,
  or `"...T..."` with a time); Duration → human string (`"64d"`); Link → target;
  File → path; `NaN`/`Infinity` → `null`.
- `--list-views` emits `{ "base": ..., "views": [{name, type, row_count}, ...] }`.

`table`/`markdown`/`csv` are human-facing renderings of the same data.

## Implemented Bases features

### Type system
String, Number, Boolean, Date, Duration, List, Object, Link, File, Regexp, plus
HTML/Image/Icon renderables and null/empty/absent handling. Truthiness/coercion
follow JavaScript: `null`, `false`, `0`, `""`, `[]` and absent properties are
falsy; `{}`, dates and durations are truthy.

### Operators
Arithmetic `+ - * / %` with parentheses (incl. `date ± duration`, `date − date`
→ Duration, `duration × number`); comparison `== != > < >= <=` across numbers,
dates, strings and links; boolean `! && ||` (with short-circuit); date arithmetic
with duration strings (`y/M/d/w/h/m/s` and their long aliases), e.g.
`due_date <= today() + "7d"`.

### Functions

| Scope | Functions |
|-------|-----------|
| **Global** | `escapeHTML` `date` `duration` `file` `html` `if` `image` `icon` `link` `list` `max` `min` `now` `number` `today` `random` |
| **Any** | `isTruthy` `isType` `toString` `isEmpty` (fallback) |
| **Date** | fields `.year .month .day .hour .minute .second .millisecond`; `date()` `format()` `time()` `relative()` `isEmpty()` |
| **String** | field `.length`; `contains` `containsAll` `containsAny` `endsWith` `startsWith` `isEmpty` `lower` `upper` `replace` `repeat` `reverse` `slice` `split` `title` `trim` |
| **Number** | `abs` `ceil` `floor` `round` `toFixed` `isEmpty` |
| **List** | field `.length`; `contains` `containsAll` `containsAny` `filter` `flat` `isEmpty` `join` `map` `reduce` `reverse` `slice` `sort` `unique`; aggregations `sum` `average`/`mean` `min` `max` `median` `stddev` (see quirks) |
| **Link** | `asFile` `linksTo` |
| **File** | fields `name basename path folder ext size ctime mtime tags links embeds backlinks properties file`; `hasTag` `inFolder` `hasLink` `hasProperty` `asLink` |
| **Object** | `isEmpty` `keys` `values` |
| **Regexp** | `matches` |

`filter`/`map`/`reduce` bind the implicit lambda variables `value`, `index`, and
(for `reduce`) `acc`. `if` and the lambda methods are lazy/short-circuiting
special forms.

`date.format()` uses **Moment.js tokens** (`YYYY MM DD HH mm ss`, `MMMM MMM Mo
Do dddd ddd hh h A a SSS X`, `[literal]`), not Python `strftime`.

### View engine
Global `filters` AND per-view `filters` (`and`/`or`/`not` trees, combined with
AND); `formulas` (with a topological dependency pass — **circular references are
a hard error**); `properties` `displayName`; `groupBy` (single property,
`ASC`/`DESC`); `sort` (ordered, multi-key, `ASC`/`DESC`); `order` (column
selection); `limit`; per-view `summaries` and base-level custom `summaries`
formulas (with the `values` binding). Default summary formulas: Average, Min,
Max, Sum, Range, Median, Stddev, Earliest, Latest, Checked, Unchecked, Empty,
Filled, Unique.

### Layouts
basecli is headless and JSON-first, so **all built-in layouts produce the same
tabular row data** — the JSON contract is layout-independent *by design* (a
`cards`, `list`, `map` or `table` view yields identical rows + chosen columns).
`view.type` is preserved in the output metadata, and the human `--format`
(`table`/`markdown`/`csv`) controls rendering independently of the layout. There
is no bespoke cards/list/map rendering (see `LIMITATIONS.md`).

`view.type` is validated against a registry: the built-ins are
`table`/`list`/`cards`/`map`, and an unrecognized type is a hard error until you
register it with `basecli.engine.register_view_type("name")` (after which it
renders as tabular data). The function registry (`basecli.functions`) is
likewise extensible by name. See `LIMITATIONS.md`.

## Faithful quirks & deviations

These match real Obsidian engine behavior (there are regression tests for them):

1. **`date − date` is a `Duration`, not a number.** Duration has no numeric
   methods, so `(due_date - today()).round()` raises
   `Cannot find function "round" on type Duration`, exactly like Obsidian. For a
   numeric day count, coerce: `((number(due_date) - number(today())) / 86400000).round()`,
   since `number(date)` is epoch milliseconds.
2. **`date.isEmpty()` always returns `false`.** Detect an empty date via
   truthiness (`if(due_date, …)`), not `isEmpty()`.
3. **`hasTag` matches nested tags** — `file.hasTag("work")` is true for
   `#work/sales`.
4. **`inFolder` matches a folder and its subfolders.**
5. **Frontmatter date typing is ambiguous.** YAML date/datetime values are
   normalized to the Date type on ingest. String-typed values are coerced to a
   Date *at comparison/arithmetic time* when the other operand is a Date (we do
   not blindly reinterpret arbitrary strings as dates at ingest — flagged
   deviation from a literal reading of the docs, chosen to avoid misclassifying
   non-date strings).
6. **`round()` is half-up toward +∞** (JS `Math.round`), e.g. `(2.5).round()` → 3,
   not Python banker's rounding.
7. Two documentation ambiguities, resolved explicitly:
   - The `reduce` example renders `acc == null | value > acc` with a single `|`
     (a markdown-table escaping artifact). The lexer accepts both `|`/`||` (OR)
     and `&`/`&&` (AND); Bases has no bitwise operators, so there is no conflict.
   - The custom-summary example uses `values.mean()`, but `mean()` is not in the
     published function table. List aggregation methods
     (`sum`/`average`/`mean`/`min`/`max`/`median`/`stddev`) are implemented so
     summary formulas work.

## Architecture

```
src/basecli/
  frontmatter.py  split YAML frontmatter; extract inline #tags, links, embeds
  vault.py        scan, file index, file properties, backlink reverse-index
  values.py       type model (Date/Duration/Link/File/Regexp…), truthiness, coercion
  lexer.py        tokenizer (regexp-vs-division disambiguation)
  parser.py       recursive-descent parser → AST
  functions.py    function registry, one impl per documented function (+ decorators)
  evaluator.py    AST walker; operators, roots, value/index/acc lambdas, if special-form
  base.py         load/validate .base; topological formula ordering + cycle detection
  engine.py       filter → sort → group → limit → select → summarize; view-type registry
  formatters.py   json / table / markdown / csv
  cli.py          argparse front door
```

## Testing

```bash
pip install -e ".[test]"   # or: pip install pytest
pytest
```

The suite includes: table-driven function/operator tests seeded from every
example on the Bases functions doc page; the `Duration` regression; an
integration test against a small, fully synthetic vault (`tests/fixtures/vault`,
fictional tasks — no personal data) with `--today 2026-06-30` asserting the
known-good `🎯 By urgency` result (3 Overdue: `migrate-legacy-database` −60,
`renew-ssl-certificate` −7, `submit-expense-report` −1; 2 Today; 2 This week
+2/+5; 1 Later +30; 4 Someday; Work=7, Personal=5, Backlog=4, Done=1; 12 rows),
the built-in `Min` and custom `customAvg` summaries, the `type == "task"` and
archive-folder exclusions, and a byte-identical determinism check.

A second synthetic fixture (`tests/fixtures/library`, a fictional book library)
proves the engine is **domain-agnostic** — no task-specific assumptions. It
exercises non-task frontmatter (`author`/`rating`/`pages`/`published`/`genre`/
`read`/`cover`), every built-in summary aggregation, list/string/date formulas
(lambda chains, `genre[0]`, `published.year`, modulo), a `cards` view, and
links/backlinks through the reverse-index. View-type registry tests confirm
unknown layouts error until `register_view_type()` accepts them.
