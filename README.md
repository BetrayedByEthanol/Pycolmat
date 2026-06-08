# customfmt

A small, project-specific Python formatting and style-checking tool.
Works **alongside** Ruff and Pyright — it does not replace them.

- `customfmt fix` – applies safe auto-formatting in place  
- `customfmt check` – checks project-specific naming and style rules (CF001–CF019)
- `customfmt doctor` – reports read-only project readiness diagnostics
- `customfmt refs` – discovers read-only project references as JSON
- `customfmt rename-symbol` – emits a project-wide rename plan as JSON, renders a diff, or applies guarded token edits

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

### `customfmt doctor` — inspect project readiness

```bash
# Human-readable diagnostics
customfmt doctor src/

# Compact machine-readable JSON
customfmt doctor src/ --json

# Indented JSON
customfmt doctor src/ --pretty
```

`customfmt doctor` is read-only and never modifies source files. It combines
existing discovery, checker, auto-fix check, indexer, and resolver behavior to
report whether a project is ready for customfmt usage. The report includes:

- Python file discovery counts, with no Python files reported as exit code 2.
- Encoding and line-ending diagnostics for invalid UTF-8, I/O read errors,
  UTF-8 BOM, CRLF, and bare CR files.
- customfmt rule status grouped by rule code, including a few example
  violations for each rule.
- Auto-fix readiness for CF009, CF011, CF013, CF018, and CF019 without writing
  files.
- Symbol tooling readiness from the indexer and resolver, including parse/file
  errors plus unresolved and dynamic reference counts. Normal unresolved
  references are summarized but do not fail doctor by themselves.
- Package/import readiness, including regular packages with `__init__.py`,
  namespace-package-like directories, and namespace package ambiguity
  diagnostics. Namespace packages are supported conservatively when scanned
  roots make module ancestry unambiguous; ambiguous namespace modules are
  reported so `refs` and `rename-symbol` can leave them unresolved.

Exit codes match the rest of the CLI: 0 means healthy/no blocking issues, 1
means style or format issues were found, and 2 means discovery, parse,
encoding, I/O, or tool/runtime errors were found.

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
- `from .module import Name`
- `from ..package.module import Name`
- `from . import module`
- `from .. import module`

Absolute and relative imports are supported when they resolve inside scanned
regular packages or namespace-package-like directories whose ancestry is
unambiguous from the scanned roots. Namespace packages are supported
conservatively inside scanned paths; ambiguous namespace-package cases,
missing modules, ambiguous modules, and imports outside scanned paths remain
unresolved and block apply by default. Relative imports that point outside
scanned paths, go beyond the package root, have ambiguous namespace ancestry,
are ambiguous, or miss their target remain `unresolved` with a reason. Imported module
attribute calls such as `module.Foo()` may be reported as `import_resolved` when
`module` is a supported local import and `Foo` is found in the imported module.
Arbitrary attribute and dynamic patterns remain dynamic or unresolved rather
than guessed:
`obj.Method()`, `self.X`, `getattr()`, `globals()`, `importlib`, and string
references are not resolved as project references.

`customfmt.symbols.project_graph.InspectProjectModules(paths)` is the public
module inspection API for callers that need to audit scanned module names before
running project reference discovery. It returns each module name with candidate
file paths, the normalized scan roots, discovery errors, and
`ambiguous_modules` for names that have more than one in-scan candidate.

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

### `customfmt rename-symbol` — plan or apply a guarded project-wide symbol rename

```bash
# Plan a rename from an exact definition/reference location
customfmt rename-symbol src/ --symbol src/models.py:1:0 --to AccountModel

# Plan by name only when exactly one supported definition matches
customfmt rename-symbol src/ --name UserModel --to AccountModel --pretty

# Write JSON to a file instead of stdout
customfmt rename-symbol src/ --name BuildValue --to MakeValue --output rename-plan.json

# Render a read-only unified diff instead of JSON
customfmt rename-symbol src/ --name UserModel --to AccountModel --diff

# Apply guarded token edits after validating every affected file
customfmt rename-symbol src/ --name UserModel --to AccountModel --apply

# Explicitly allow applying safe edits when warnings/skips are present
customfmt rename-symbol src/ --name UserModel --to AccountModel --apply --allow-incomplete
```

`customfmt rename-symbol` is v1 conservative and stable enough for
guarded use. It is not an IDE-level refactor engine, and it intentionally does
not support every Python reference pattern. It emits JSON by default, pretty
JSON with `--pretty`, writes JSON with `--output PATH`, renders a read-only
unified diff with `--diff`, and applies guarded token edits with `--apply`.
When `--diff` is used, JSON is not printed and source files are not modified.
Diff mode is read-only, so it renders proposed token edits to stdout without
applying them to source files. `--apply` reuses the same token renderer and
validation path as diff mode: every affected file is rendered first, every
planned edit must target an existing `NAME` token whose text matches the
recorded `old` value, and no source file is written if validation fails for
any affected file. Apply mode writes files with UTF-8 LF normalization and
prints `renamed <path>` for each written file; if the plan has no edits, it
prints nothing and exits 0. By default, `--apply` refuses to write and exits 2
when the plan contains any `warnings`, `skipped`, `unresolved_references`, or
`dynamic_references`. Use `--apply --allow-incomplete` only when you have
reviewed the JSON or diff and want to apply the safe planned token edits while
leaving incomplete, skipped, or dynamic sites untouched. Always run tests after
applying a project-wide rename. `--allow-incomplete` is apply-only; using it
with JSON plan mode or `--diff` exits 2. `--apply` cannot be combined with
`--diff`, `--output`, or `--pretty`. `--diff` cannot be combined with
`--output`; that incompatible option pair exits with code 2 before writing any
output file. `--pretty` only affects JSON output and is ignored in diff mode.
The command uses `customfmt refs` project reference results as its source of
truth, then reports, renders, or applies exact token edit sites. If `--name`
matches multiple supported definitions, the command returns an ambiguity error
and requires `--symbol PATH:LINE:COL`.

#### `rename-symbol` v1 workflow examples

```bash
# Preview the JSON token edit plan
customfmt rename-symbol src/ --name UserModel --to AccountModel --pretty

# Preview the unified diff without writing files
customfmt rename-symbol src/ --name UserModel --to AccountModel --diff

# Apply only when the plan is complete and guarded validation succeeds
customfmt rename-symbol src/ --name UserModel --to AccountModel --apply

# Explicitly apply safe edits from an incomplete plan after review
customfmt rename-symbol src/ --name UserModel --to AccountModel --apply --allow-incomplete
```

`--allow-incomplete` does not make unsupported references editable. It applies
only safe planned token edits and leaves warnings, skipped, unresolved, and
dynamic sites untouched.

#### `rename-symbol` v1 support matrix

Supported v1 rename sites are conservative:

| Pattern | Status | Notes |
|---------|--------|-------|
| Class definitions | Supported | Renames the class definition token. |
| Function definitions | Supported | Renames module-level and nested function definition tokens when selected as supported functions. |
| Module-level declarations | Supported | Renames direct module-level assignment or annotation names. |
| `from module import Name` | Supported | Renames the imported binding when the import resolves to the selected local project symbol, including unambiguous namespace-package modules inside scanned paths. |
| `from module import Name as Alias` | Supported alias behavior | Renaming the original target edits the exported definition but does not rewrite `Alias`; selecting the alias symbol can rename the alias binding and its safe alias references. |
| `import module; module.Function()` | Supported | Renames only the final attribute token when the module import resolves safely. |
| Safe relative imports | Supported | `from .module import Name`, `from ..package.module import Name`, `from . import module`, and `from .. import module` resolve only when the target module exists unambiguously inside scanned regular packages or namespace-package-like directories. |
| Annotations | Supported | Safe resolved annotation name tokens are planned. |
| Constructor and call references | Supported | Safe resolved call tokens such as `UserModel()` and `BuildValue()` are planned. |

Unsupported v1 patterns are excluded from edits and reported as skipped,
unresolved, or dynamic when detected:

| Pattern | Status | Notes |
|---------|--------|-------|
| Local variables | Unsupported | Use `customfmt rename` for local variable cleanup. |
| Methods | Unsupported | Do not rename method definitions with `rename-symbol`. |
| Instance attributes | Unsupported | Includes direct attribute definitions and reads. |
| Class attributes | Unsupported | Class-body declarations are not project-wide rename targets. |
| `self.X` | Unsupported | Treated as dynamic/attribute-based. |
| `obj.Method()` | Unsupported | Dynamic attribute calls are not guessed. |
| Wildcard imports | Unsupported | `from module import *` references stay unresolved for rename purposes. |
| Unresolved imports | Unsupported | Relative imports outside scanned paths, relative imports beyond the package root, ambiguous namespace-package cases, ambiguous imports, or missing targets stay unresolved and block apply by default. |
| String references | Unsupported | Strings are never rewritten. |
| `getattr` / `globals` / `importlib` / `eval` / `exec` | Unsupported | Dynamic patterns are skipped or left unresolved rather than guessed. |
| Unresolved external imports | Unsupported | External imports that cannot be safely resolved are blocked by default in apply mode. |

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

For this repository, run the project formatter/checker rather than generic
Ruff formatting. The formatter owns alignment and the custom naming rules.

```bash
python -m pip install -e .
ruff check customfmt/ tests/
try-auto-format customfmt/ tests/
check-format customfmt/ tests/
pytest
```

### CI workflow (read-only checks)

The release CI keeps linting, test coverage, and read-only smoke checks
separate. The smoke commands exercise indexing, resolving, reference lookup,
and rename planning without applying edits.

```bash
python -m pip install -e .
ruff check customfmt/ tests/
try-auto-format --check customfmt/ tests/
check-format customfmt/ tests/
pytest --cov=customfmt --cov-report=term-missing
create-index customfmt/ --pretty
resolve-index customfmt/ --pretty
customfmt refs customfmt/ --name ResolveFile --pretty
customfmt rename-symbol customfmt/ --name ResolveFile --to ResolvePath --diff
```

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
          python -m pip install --upgrade pip
          python -m pip install ruff
          python -m pip install -e .

      - name: Ruff lint
        run: ruff check customfmt/ tests/

      - name: customfmt format check
        run: try-auto-format --check customfmt/ tests/

      - name: customfmt style check
        run: check-format customfmt/ tests/
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
      - run: |
          python -m pip install --upgrade pip
          python -m pip install ruff
          python -m pip install -e .
      - run: ruff check customfmt/ tests/
      - run: try-auto-format --check customfmt/ tests/
      - run: check-format customfmt/ tests/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "${{ matrix.python-version }}" }
      - run: |
          python -m pip install --upgrade pip
          python -m pip install -e . pytest pytest-cov
      - run: pytest --cov=customfmt --cov-report=term-missing

  smoke:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: |
          python -m pip install --upgrade pip
          python -m pip install -e .
      - run: create-index customfmt/ --pretty
      - run: resolve-index customfmt/ --pretty
      - run: customfmt refs customfmt/ --name ResolveFile --pretty
      - run: customfmt rename-symbol customfmt/ --name ResolveFile --to ResolvePath --diff
```

---

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
