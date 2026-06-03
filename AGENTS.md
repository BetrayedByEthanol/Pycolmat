# AGENTS.md

## Purpose

This repository contains `customfmt`, a project-specific Python formatting, style-checking, symbol-indexing, resolver, and rename-planning tool.

Any coding agent working on this repository must follow the repository’s own custom formatting rules. Do **not** produce standard Black/Ruff-formatted Python if that conflicts with `customfmt`.

The formatter is both the project and the standard for this project.

---

## Required workflow

Before opening or updating a PR, run:

```bash
python -m pip install -e .
ruff check customfmt/ tests/
try-auto-format customfmt/ tests/
check-format customfmt/ tests/
pytest
```

For verification-only CI behavior, run:

```bash
ruff check customfmt/ tests/
try-auto-format --check customfmt/ tests/
check-format customfmt/ tests/
pytest
```

If changing resolver, indexer, or rename-planner behavior, also inspect JSON output manually when useful:

```bash
create-index customfmt/ --pretty
resolve-index customfmt/ --pretty
customfmt rename --check customfmt/ --json
```

---

## Formatting rules agents must follow

### Python indentation

Use **3 spaces** for indentation.

Correct:

```python
def Example():
   Value = 1
   return Value
```

Incorrect:

```python
def example():
    value = 1
    return value
```

Do not use tabs.

---

## Naming rules

The project intentionally uses custom naming conventions.

| Item                         | Required style                      |
| ---------------------------- | ----------------------------------- |
| File names                   | `snake_case.py`                     |
| Classes                      | `PascalCase`                        |
| Functions / methods          | `PascalCase`                        |
| Parameters                   | `snake_case`, except `self` / `cls` |
| Local variables              | `snake_case`                        |
| Instance attributes `self.X` | `PascalCase`                        |
| Module-level declarations    | `PascalCase` or `UPPER_CASE`        |
| Class-body declarations      | `PascalCase` or `UPPER_CASE`        |

Examples:

```python
class RenamePlan:
   FilePath = ""
   DEFAULT_TIMEOUT = 30

   def ToDict(self) -> dict:
      result = {}
      return result
```

Do not “fix” this project into standard Python naming style. For example, do **not** rename methods like `ToDict()` to `to_dict()`.

---

## Alignment rules

The repository uses deliberate vertical alignment.

### `self.X = value` alignment

Correct:

```python
self.Name        = name
self.Description = description
self.Enabled     = True
```

### Class-body declaration alignment

Assignment-only block:

```python
class Repo:
   TableName  = "Artikel"
   References = {}
   TypeRef    = {}
   Model      = ArtikelModel
   Pk         = "ID"
```

Typed block:

```python
class ArtikelModel:
   ID          : int
   Name        : str
   Description : str
```

Mixed typed / assigned block:

```python
class Example:
   ID            : int
   Name          : str = ""
   Enabled             = True
   VeryLongField : Decimal
   Count         : int = 0
```

Do not remove alignment because Ruff, Black, or personal preference would normally collapse spacing.

---

## Line endings and encoding

All Python files must be:

* UTF-8
* no UTF-8 BOM
* LF line endings only
* exactly one final newline

Do not introduce CRLF files. Do not save Python files as Windows-1252, CP1252, or other non-UTF-8 encodings.

---

## Ruff usage

Ruff is used for linting only. Do **not** use `ruff format` on this repository unless explicitly requested.

`customfmt` owns formatting and alignment.

Expected order:

```bash
ruff check customfmt/ tests/
try-auto-format customfmt/ tests/
check-format customfmt/ tests/
pytest
```

---

## Architecture guidelines

### Keep responsibilities separated

| Area                  | Responsibility                     |
| --------------------- | ---------------------------------- |
| `formatter.py`        | safe deterministic formatting      |
| `checker.py`          | check/report style rules           |
| `indexer.py`          | raw AST symbol indexing            |
| `symbols/resolver.py` | per-file lexical symbol resolution |
| `rename_plan.py`      | safe rename planning               |
| `cli.py`              | command wiring only                |

Do not mix rewrite logic into the resolver.
Do not mix project-wide rename logic into the local rename planner.
Do not make `try-auto-format` perform semantic refactors.

---

## Formatter safety rules

`try-auto-format` may only perform safe deterministic changes:

* LF normalization
* trailing whitespace removal
* final newline normalization
* `self.X = value` alignment
* class-body declaration alignment

It must not rename symbols, move code, hoist declarations, rewrite imports, or change semantics.

---

## Rename planner rules

Rename planning is currently v1 and must remain conservative.

Allowed:

* local variables inside one function/method scope
* local assignment targets
* annotated local assignments
* augmented assignments
* `for` targets
* `with ... as` targets
* `except ... as` targets

Not allowed:

* functions
* methods
* classes
* parameters
* imports
* module declarations
* class declarations
* `self.X` attributes
* globals
* nonlocals
* cross-file symbols
* dynamic references

Skip an entire function if it contains:

```python
global X
nonlocal X
locals()
globals()
vars()
eval()
exec()
```

Do not rewrite strings or comments. Use token-position rewriting only.

---

## Resolver rules

The resolver is read-only.

It may:

* build scopes
* collect definitions
* collect reads/writes/calls/annotations
* resolve per-file lexical references
* mark unresolved or dynamic references

It must not:

* rewrite files
* perform project-wide import resolution yet
* pretend `self.X` or `obj.Method()` is safely resolved
* rename anything directly

Attribute calls should remain dynamic unless a later explicit project-wide resolver safely proves their target.

---

## Adding new rules

When adding a new `CF###` rule:

1. Add the rule implementation.
2. Add tests.
3. Update README rule tables.
4. Ensure `--ignore CF###` works if applicable.
5. Decide whether the rule is:

   * check-only
   * auto-fixable
   * both
6. Ensure `try-auto-format --check` and `check-format` agree where appropriate.

---

## Tests required for changes

When changing formatter behavior, add tests for:

* check mode
* fix mode
* diff mode if relevant
* ignored-rule behavior if relevant
* CRLF/LF preservation where applicable

When changing resolver behavior, add tests for:

* definitions
* reads
* writes
* unresolved refs
* dynamic refs
* annotations
* decorators
* nested scopes
* global/nonlocal behavior

When changing rename planner behavior, add tests for:

* generated plan items
* skipped items/scopes
* rewritten output
* strings/comments unchanged
* collision handling
* JSON output if applicable

---

## CLI behavior

Exit codes:

| Code | Meaning                                  |
| ---: | ---------------------------------------- |
|  `0` | success                                  |
|  `1` | formatting/style/rename candidates found |
|  `2` | tool/runtime error                       |

Do not expose internal Python tracebacks for expected user-facing errors. Return structured errors where possible.

---

## Documentation requirements

Any user-visible behavior change must update README.

This includes:

* new commands
* new flags
* new rule codes
* changed exit behavior
* changed formatter behavior
* changed resolver/indexer/rename output schema

---

## PR checklist

Before submitting a PR, confirm:

```bash
ruff check customfmt/ tests/
try-auto-format --check customfmt/ tests/
check-format customfmt/ tests/
pytest
```

Also confirm that generated code follows this project’s custom style:

* 3-space indentation
* PascalCase functions/methods/classes
* snake_case locals/parameters
* PascalCase or UPPER_CASE declarations
* aligned class/self assignment blocks
* LF + UTF-8 without BOM

If a change intentionally violates an existing customfmt rule, update the rule, tests, and README in the same PR.
