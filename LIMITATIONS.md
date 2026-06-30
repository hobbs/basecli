# Limitations & extension points

`basecli` reimplements the documented Obsidian Bases engine for **read-only,
headless rendering**. The following are intentionally out of scope.

## Intentionally out of scope

- **Live editing.** `basecli` reads notes and renders views; it never writes to
  notes or `.base` files. (An agent consuming the output is expected to open and
  edit the source notes itself — every row carries `file.path`/`file.abspath`.)
- **Layout-specific human rendering.** All built-in layouts
  (`table`/`list`/`cards`/`map`) produce the **same tabular row data** — basecli
  is headless and JSON-first, so the row set is layout-independent by design.
  There is no bespoke cards (image + fields), list (bulleted lines), or map
  (coordinate/tile/marker) rendering; `--format` controls the human output
  instead. `view.type` is preserved in the output metadata.
- **Plugin-supplied functions and view types.** Only the documented built-in
  function library and the `table`/`list`/`cards`/`map` layouts ship. An
  unrecognized `view.type` is a **hard error** until registered (below);
  community-plugin functions are not bundled — but both registries are extensible.
- **Renderable fidelity.** `html()`, `image()`, `icon()`, and `link()` produce
  typed wrapper values whose `display` is their source/target string. There is no
  actual HTML/image/icon rendering — this is a CLI.
- **`this` without `--this`.** There is no live editor, so `this.*` resolves only
  when `--this PATH` is supplied; otherwise `this` is `null`.
- **Obsidian's exact relative-time wording.** `date.relative()` returns a
  reasonable `"N days ago"` / `"in N days"` string but is not guaranteed to match
  Moment.js phrasing token-for-token.
- **Property type declarations.** Obsidian knows a property's declared type from
  vault config; `basecli` infers types from values (YAML date/datetime → Date;
  date-like strings coerced at comparison time). See deviation #5 in the README.

## Known deviations (documented in README "Faithful quirks")

- String values are **not** blindly reinterpreted as Dates at ingest; coercion
  happens at comparison/arithmetic time against a Date operand.
- `|`/`&` are accepted as aliases for `||`/`&&` (resolves a doc ambiguity).
- List aggregation methods (`sum`/`average`/`mean`/`min`/`max`/`median`/`stddev`)
  are implemented to support summary formulas, though `mean()` is the only one
  the docs reference (and it is not in the function table).

## How to extend the registries

### Add a function

Functions live in `basecli/functions.py` and register by name (globals) or by
`(type, name)` (type methods) via decorators. Example — add a `String.snake()`
method and a `slugify()` global:

```python
from basecli.functions import method, global_fn
from basecli.values import to_string

@method("string", "snake")
def _s_snake(ctx, recv, args):
    return recv.strip().lower().replace(" ", "_")

@global_fn("slugify")
def _g_slugify(ctx, args):
    import re
    return re.sub(r"[^a-z0-9]+", "-", to_string(args[0]).lower()).strip("-")
```

Method functions receive `(ctx, recv, args)`; globals receive `(ctx, args)`,
where `args` is the list of already-evaluated argument values. `ctx` exposes
`ctx.env` (vault, `today`, `now`, formulas, `this_obj`) and `ctx.resolve_file()`.
Dispatch tries `(type_name(recv), name)`, then the any-type table, then raises
`Cannot find function "<name>" on type <Type>`.

Lazy/short-circuiting forms (`if`, `filter`, `map`, `reduce`) are special forms
in `evaluator.py` because they need unevaluated argument ASTs; add new lazy forms
there.

### Add a view type

`view.type` is validated against `basecli.engine.VIEW_TYPES`; an unknown type
raises `SchemaError`. Register a plugin layout by name so its views are accepted
(they render as tabular data, like every built-in layout):

```python
from basecli.engine import register_view_type
register_view_type("timeline")
```

To go further and give a layout a bespoke human rendering, add a branch on
`view.type` in `basecli/formatters.py`. The JSON contract stays layout-independent
regardless.
