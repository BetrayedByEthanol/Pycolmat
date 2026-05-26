# customfmt

A small, project-specific Python formatting and style-checking tool.
Works **alongside** Ruff and Pyright — it does not replace them.

- `customfmt fix` – applies safe auto-formatting in place  
- `customfmt check` – checks project-specific naming and style rules (CF001–CF012)

---

## Installation

```bash
# From the tools/customfmt directory:
pip install .

# Or editable (development):
pip install -e .
```

Three console scripts are installed:

| Script            | Equivalent              |
|-------------------|-------------------------|
| `customfmt`       | main entry point        |
| `try-auto-format` | alias for `customfmt fix`   |
| `check-format`    | alias for `customfmt check` |

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
4. Ensure exactly one final newline  

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

- contains a `global` or `nonlocal` declaration,
- calls `locals()`, `globals()`, `vars()`, `eval()`, or `exec()`,
- would produce a name collision with an existing local, parameter,
  imported name, or Python builtin, or
- has two bad names that map to the same `snake_case` target.

Nested functions and classes are not renamed in v1; each top-level
function scope is handled independently.


---

## Rules

### Auto-fix rules (applied by `customfmt fix`)

| Rule                   | Description                                                   |
|------------------------|---------------------------------------------------------------|
| trailing-whitespace    | Remove trailing spaces/tabs on every line                     |
| self-alignment         | Align contiguous `self.X = value` blocks (same indent)        |
| final-newline          | Ensure exactly one newline at end of file                     |
| line-endings           | Convert CRLF and bare CR line endings to LF                   |

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
