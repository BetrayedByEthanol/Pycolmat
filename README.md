# customfmt

A small, project-specific Python formatting and style-checking tool.
Works **alongside** Ruff and Pyright — it does not replace them.

- `customfmt fix` – applies safe auto-formatting in place  
- `customfmt check` – checks project-specific naming and style rules (CF001–CF019)
- `customfmt refs` – discovers read-only project references as JSON
- `customfmt rename-symbol` – emits a read-only project-wide rename plan as JSON or unified diff

---

## Installation

```bash
# From the tools/customfmt directory:
pip install .

# Or editable (development):
pip install -e .
```

Five console scripts are installed:

| Script            | Equivalent              |
|-------------------|-----------------------------|
| `customfmt`       | main entry point        |
| `try-auto-format` | alias for `customfmt fix`   |
| `check-format`    | alias for `customfmt check` |
| `create-index`    | alias for `customfmt index` |
| `resolve-index`   | alias for `customfmt resolve` |

**Requirements:** Python ≥ 3.11, no third-party dependencies.

---

## Commands

### `customfmt fix` — auto-format files

```bash
# Fix all .py files under src/
customfmt fix src/

# Fix a single file
customfmt fix src/models/user_model.py

# Check what would change without writing (CI-friendly)
customfmt fix --check src/

# Show a unified diff without writing
customfmt fix --diff src/

# Suppress per-file output
customfmt fix --quiet src/
```

Auto-fix rules applied (in order):

1. Convert CRLF / CR line endings to LF  
2. Remove trailing whitespace  
3. Align contiguous `self.X = value` blocks  
4. Align class-body declaration blocks  
5. Ensure exactly one final newline  

### `customfmt check` — check style rules

```bash
# Check src/ and tests/
customfmt check src/ tests/

# Output as JSON (useful for tooling)
customfmt check --json src/

# Quiet (only exit code, no output)
customfmt check --quiet src/
```

Output format:

```
path/to/file.py:line:col CODE message
```

Example:

```
src/user_model.py:4:1 CF003 function name must be PascalCase: 'calculate_total'
src/user_model.py:7:1 CF010 indentation of 4 spaces is not a multiple of 3
```

---

### `customfmt rename` — safe local variable rename

```bash
# Report rename candidates (exits 1 if any found)
customfmt rename --check src/

# Show unified diff of proposed renames without writing
customfmt rename --diff src/

# Apply renames in place (exits 0)
customfmt rename --apply src/
```

Renames non-`snake_case` local variables (CF005) to `snake_case` within
each function scope. Output format:

```
src/user_model.py:4:7 RENAME local variable 'TotalCount' -> 'total_count'
```

**Safety rules** — a function is skipped entirely if it:

- contains a `global` or `nonlocal` declaration, or
- calls `locals()`, `globals()`, `vars()`, `eval()`, or `exec()`.

An individual rename is skipped if it would:

- produce a name collision with a visible local, parameter, import,
  parent/module declaration, or Python builtin,
- collide with another bad name that maps to the same `snake_case` target, or
- patch the same token position as another rename to a different target name.

Nested functions and classes are planned independently without crossing
scope boundaries. In JSON output, each item keeps the backward-compatible
`sites` list and also reports `definition_sites`, `read_sites`,
`write_sites`, and `all_sites`; the plan also includes `skipped` entries.


---

### `customfmt index` — build a symbol index

```bash
# Index all .py files under src/
customfmt index src/

# Pretty-print JSON
customfmt index --pretty src/

# Write to a file
customfmt index --output index.json src/
```

`create-index` is an alias for `customfmt index`.

Output is always JSON with a `files` array and an `errors` array.  Each
file entry contains a `symbols` list with `kind`, `name`, `qualified_name`,
`file`, `line`, `col`, `scope`, and `extra` fields.

---

### `customfmt resolve` — build a resolved symbol graph

```bash
# Resolve all .py files under src/
customfmt resolve src/

# Pretty-print JSON
customfmt resolve --pretty src/

# Write to a file
customfmt resolve --output resolve.json src/
```

`resolve-index` is an alias for `customfmt resolve`.

Output is JSON with a `files` array and an `errors` array.  Each file entry
contains `scopes`, `definitions`, `references`, and a `summary`.  References
include a `resolved_to` field when the name was resolved within the file, and
an `unresolved` flag when no definition was found.


---

### `customfmt refs` — find read-only project references

```bash
# Find definitions and references by name
customfmt refs src/ --name UserModel

# Find references to the symbol at PATH:LINE:COL
customfmt refs src/ --symbol src/models.py:1:6

# Pretty-print JSON
customfmt refs src/ --name BuildValue --pretty

# Write JSON to a file
customfmt refs src/ --name BuildValue --output refs.json
```

`customfmt refs` is a project-level reference discovery foundation. It is
read-only and does not implement project-wide rename. The command reuses the
per-file resolver, then conservatively resolves these import forms between
files when the target module is present in the scanned paths:

- `from package.module import Name`
- `from package.module import Name as Alias`
- `import package.module as alias`
- `import package.module`

Relative imports are reported as unresolved in this v1 foundation with
`relative_import_unresolved` as the reason. Imported module attribute calls such
as `module.Foo()` may be reported as `import_resolved` when `module` is a
supported local import and `Foo` is found in the imported module. Arbitrary
attribute and dynamic patterns remain dynamic or unresolved rather than guessed:
`obj.Method()`, `self.X`, `getattr()`, `globals()`, `importlib`, and string
references are not resolved as project references.

Output is always JSON with `definitions`, `references`,
`unresolved_references`, `dynamic_references`, `errors`, and `summary`. Every
reported definition or reference includes a `confidence` value:

| Confidence        | Meaning                                             |
|-------------------|-----------------------------------------------------|
| `local_resolved`  | resolved by the existing per-file lexical resolver  |
| `import_resolved` | resolved through a supported import between files   |
| `unresolved`      | no safe local or import target was found            |
| `dynamic`         | skipped because the reference is dynamic/attribute-based |

---

### `customfmt rename-symbol` — plan a read-only project-wide symbol rename

```bash
# Plan a rename from an exact definition/reference location
customfmt rename-symbol src/ --symbol src/models.py:1:0 --to AccountModel

# Plan by name only when exactly one supported definition matches
customfmt rename-symbol src/ --name UserModel --to AccountModel --pretty

# Write JSON to a file instead of stdout
customfmt rename-symbol src/ --name BuildValue --to MakeValue --output rename-plan.json

# Render a read-only unified diff instead of JSON
customfmt rename-symbol src/ --name UserModel --to AccountModel --diff
```

`customfmt rename-symbol` emits JSON by default, pretty JSON with `--pretty`,
writes JSON with `--output PATH`, and renders a read-only unified diff with
`--diff`. When `--diff` is used, JSON is not printed and source files are not
modified. Diff mode is read-only, so it renders proposed token edits to stdout
without applying them to source files. `--diff` cannot be combined with
`--output`; that incompatible option pair exits with code 2 before writing any
output file. `--pretty` only affects JSON output and is ignored in diff mode.
The command uses `customfmt refs` project reference results as its source of
truth, then reports or renders exact token edit sites that a future applier
could use. If `--name` matches
multiple supported definitions, the command returns an ambiguity error and
requires `--symbol PATH:LINE:COL`.

Supported v1 targets are conservative:

- class definitions,
- function definitions,
- module-level declarations,
- safely resolved `from module import Name` bindings, and
- safely resolved imported module attribute calls such as `module.Function()`,
  where only the attribute token is planned for editing.

Unsupported or unsafe references are excluded from edits and reported in
`skipped`, `unresolved_references`, or `dynamic_references`: local variables
(use `customfmt rename` for those), methods, instance/class attributes, dynamic
attribute calls, unresolved imports, relative imports, wildcard imports, string
references, `getattr()`, `globals()`, and `importlib` patterns.

The JSON shape is:

```json
{
  "query": {"type": "name", "name": "UserModel"},
  "target": {"name": "UserModel", "kind": "class"},
  "new_name": "AccountModel",
  "files_affected": ["src/models.py"],
  "edits": [
    {"file": "src/models.py", "line": 1, "col": 6, "old": "UserModel", "new": "AccountModel", "kind": "definition:class"}
  ],
  "skipped": [],
  "unresolved_references": [],
  "dynamic_references": [],
  "warnings": [],
  "summary": {"edits": 1}
}
```

New names are validated with the project naming rules: class/function/import
alias targets require `PascalCase`; module declarations require `PascalCase`
or `UPPER_CASE`. Collision checks add safety warnings when the same scope or
an importing file already binds the requested new name.


---

## Rules

### Auto-fix rules (applied by `customfmt fix`)

| Code  | Rule                     | Description                                              |
|-------|--------------------------|----------------------------------------------------------|
| CF011 | line-endings             | Convert CRLF / CR line endings to LF                     |
| CF018 | trailing-whitespace      | Remove trailing spaces/tabs on every line                |
| CF009 | self-assignment-align    | Align contiguous `self.X = value` blocks                 |
| CF013 | class-body-align         | Align class-body declaration blocks                      |
| CF019 | final-newline            | Ensure exactly one newline at end of file                |

### Check-only rules (reported by `customfmt check`)

| Code  | Description                                                       |
|-------|-------------------------------------------------------------------|
| CF001 | File name must be `snake_case.py`                                 |
| CF002 | Class name must be `PascalCase`                                   |
| CF003 | Function and method names must be `PascalCase`                    |
| CF004 | Parameter names must be `snake_case` (except `self`/`cls`)       |
| CF005 | Local variable names must be `snake_case`                         |
| CF006 | Instance attributes (`self.X`) must be `PascalCase`               |
| CF007 | Module-level declarations must be `PascalCase` or `UPPER_CASE`     |
| CF008 | Class-body declarations must be `PascalCase` or `UPPER_CASE`      |
| CF009 | `self.X = value` assignment blocks must be aligned                |
| CF010 | Indentation must use spaces; width must be a multiple of 3        |
| CF011 | File must use LF line endings only (no CRLF or bare CR)           |
| CF012 | File must be valid UTF-8 without BOM                              |
| CF013 | Class-body declaration block must be aligned                      |
| CF014 | Top-level declarations must appear before class/function defs     |
| CF015 | Class-body declarations must appear before methods/nested classes |
| CF018 | Trailing whitespace on any line                                   |
| CF019 | Missing newline at end of file                                    |

### Naming convention reference

| Convention  | Pattern                                      | Example            |
|-------------|----------------------------------------------|--------------------|
| `snake_case`| lowercase words separated by underscores     | `user_name`        |
| `PascalCase`| starts uppercase, no underscores             | `UserModel`        |
| `UPPER_CASE`| uppercase words separated by underscores     | `DEFAULT_TIMEOUT`  |

### CF007 / CF008 declaration naming

Every direct `Assign` or `AnnAssign` at module level (CF007) or in a class
body (CF008) must use either `PascalCase` or `UPPER_CASE`.  The rule applies
regardless of what is on the right-hand side — Python has no true
const/var distinction, so literal vs non-literal RHS is not relevant.

```python
# Module level — all valid (CF007)
AppConfig      = LoadConfig()
DEFAULT_TIMEOUT = 30
TableName      = "orders"

# Module level — all invalid (CF007)
appConfig      = LoadConfig()   # camelCase
default_timeout = 30            # snake_case
tablename      = "orders"       # lowercase

# Class body — all valid (CF008)
class Repo:
    TableName  = "ArtikelVertrieb"
    TABLE_NAME = "ArtikelVertrieb"
    TypeRef    = {}

# Class body — all invalid (CF008)
class Repo:
    tableName = "ArtikelVertrieb"   # camelCase
    type_ref  = {}                  # snake_case
    pk        = "ID"                # lowercase
```

Dunder names (`__version__`, `__all__`, `__slots__`, etc.) are exempt.

---

## Before / after example

**Before** (`customfmt fix`):

```python
class UserModel:
    def __init__(self):
        self.Name = ""
        self.Descr = None
        self.CompType = 0
        self.ShowInDatasheet = True   
```

**After**:

```python
class UserModel:
   def __init__(self):
      self.Name            = ""
      self.Descr           = None
      self.CompType        = 0
      self.ShowInDatasheet = True
```

---

## CI / CD workflow

### Local developer workflow

```bash
ruff check --fix src/
ruff format src/
try-auto-format src/
check-format src/
pyright
```

### CI workflow (read-only checks)

```bash
ruff check src/
ruff format --check src/
try-auto-format --check src/
check-format src/
pyright
```

### `--ignore` — suppress specific rules

Any `customfmt fix` or `customfmt check` command accepts `--ignore` to
suppress specific rule codes. This is useful in CI when introducing rules
gradually or when a project legitimately deviates from a rule.

```bash
# Suppress a single rule
check-format src/ --ignore CF014

# Suppress multiple rules (comma-separated)
check-format src/ --ignore "CF014,CF015"

# Suppress multiple rules (semicolon-separated)
check-format src/ --ignore "CF014;CF015"

# Repeat the flag
check-format src/ --ignore CF014 --ignore CF015

# Skip class-body alignment in fix mode
try-auto-format src/ --ignore CF013

# Check but ignore hoisting violations
try-auto-format --check src/ --ignore CF013

# Case-insensitive
check-format src/ --ignore cf014
```

`--ignore` is accepted by `customfmt fix`, `customfmt check`, `try-auto-format`,
and `check-format`. It is **not** available on `customfmt rename` or
`customfmt index`.

In fix write mode, ignored fix rules are also skipped (the transformation is
not applied), not just suppressed in output.

---

### Gitea Actions example

```yaml
# .gitea/workflows/ci.yaml
name: CI
on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install tools
        run: |
          pip install ruff pyright
          pip install tools/customfmt/

      - name: Ruff lint
        run: ruff check src/

      - name: Ruff format check
        run: ruff format --check src/

      - name: customfmt format check
        run: try-auto-format --check src/

      - name: customfmt style check
        run: check-format src/

      - name: Pyright
        run: pyright
```

### GitHub Actions example

```yaml
# .github/workflows/ci.yaml
name: CI
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install ruff pyright && pip install tools/customfmt/
      - run: ruff check src/
      - run: ruff format --check src/
      - run: try-auto-format --check src/
      - run: check-format src/
      - run: pyright
```

---

## Exit codes

| Code | Meaning                                                          |
|------|------------------------------------------------------------------|
| `0`  | Success                                                          |
| `1`  | Violations found (`check`) or changes needed (`fix --check`)    |
| `2`  | Tool / runtime error (bad path, I/O error, no .py files found)  |

### Encoding and exit codes

`check-format` (and `customfmt check`) treats encoding problems as **style
violations**, not tool errors. A file with a UTF-8 BOM or invalid UTF-8 bytes
is reported as CF012 and causes **exit 1** — the same as any other rule
violation. This lets CI treat encoding issues identically to naming or
indentation issues.

`try-auto-format` (and `customfmt fix`) refuses to touch a file whose
encoding is broken:

- **Invalid UTF-8** — the bytes cannot be decoded at all; rewriting the file
  would corrupt or lose data. Exit **2**.
- **UTF-8 BOM** — silently removing a BOM could change the meaning of files
  that depend on it (some Windows tools use the BOM as an encoding marker).
  Exit **2** so the developer makes the choice explicitly.

In both cases a clear error message is printed to `stderr` identifying the
file and the problem.

---

## Project structure

```
tools/customfmt/
├── pyproject.toml
├── README.md
├── customfmt/
│   ├── __init__.py
│   ├── cli.py           # argparse CLI + alias entry points
│   ├── formatter.py     # orchestrates auto-fix rules
│   ├── checker.py       # orchestrates check-only rules
│   ├── discovery.py     # file collection with ignored-dir filtering
│   ├── io.py            # UTF-8 / LF read-write helpers
│   ├── renamer.py       # safe local-variable rename (CF005)
│   ├── types.py         # Violation dataclass
│   └── rules/
│       ├── trailing_whitespace.py
│       ├── final_newline.py
│       ├── line_endings.py              # fix + CF011 / CF012
│       ├── self_assignment_alignment.py # fix + CF009
│       ├── indentation.py               # CF010
│       └── naming.py                    # CF001–CF008 (AST-based)
└── tests/
    ├── test_cli.py
    ├── test_discovery.py
    ├── test_final_newline.py
    ├── test_line_endings.py
    ├── test_rename.py
    ├── test_trailing_whitespace.py
    ├── test_self_assignment_alignment.py
    ├── test_indentation.py
    └── test_naming.py
```

---

## Development

```bash
# Install in editable mode
pip install -e tools/customfmt/

# Run tests
cd tools/customfmt && pytest

# Run with coverage
pytest --cov=customfmt --cov-report=term-missing

# Self-check
check-format customfmt/ tests/
```
