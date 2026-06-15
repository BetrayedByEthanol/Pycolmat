# Changelog

## v0.2.0 - 2026-06-15

This release expands `customfmt rename-symbol` with conservative method rename support.

### Added
- Safe method reference resolution for:
  - `self.Method()`
  - `cls.Method()`
  - same-file `ClassName.Method(...)`
  - safely imported `ClassName.Method(...)`
- JSON and diff planning for safe method renames.
- Guarded method `--apply` for complete safe method plans.
- Namespace-package support for project refs and rename-symbol.
- `customfmt doctor` readiness diagnostics.
- Public `InspectProjectModules(paths)` inspection API.

### Safety
- Method apply is all-or-nothing with validation before writing.
- `--allow-incomplete` does not bypass method safety guards.
- Dynamic, inherited, `super()`, arbitrary `obj.Method()`, `getattr()`, string, unresolved, skipped, warning, edit-conflict, and collision cases remain blocked.

## v0.1.0 - 2026-06-05

- custom formatter/checker
- indexer
- resolver
- refs
- local rename
- project-wide rename-symbol plan/diff/apply
- guardrails
- relative import resolution for project refs and rename-symbol
- GitHub Actions CI with lint/test/smoke jobs

### Release checklist

```bash
ruff check customfmt/ tests/
try-auto-format --check customfmt/ tests/
check-format customfmt/ tests/
pytest
create-index customfmt/ --pretty
resolve-index customfmt/ --pretty
customfmt refs customfmt/ --name ResolveFile --pretty
customfmt rename-symbol customfmt/ --name ResolveFile --to ResolvePath --diff
```
